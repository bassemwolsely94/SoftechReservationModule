from . import T

_ITEMS_TAB = T('افتح تبويب «تصنيف الأصناف».', 'Open the "Item categories" tab.')

MODULE = {
    'key': 'code_maps', 'group': 'admin', 'icon': '🏷️',
    'brief': T('معنى أكواد SOFTECH لقنوات البيع وتصنيفات الأصناف كما يفهمها النظام، وتعديلها.',
               'What the SOFTECH sales-channel and item-category codes mean to the system, and changing it.'),
    'title': T('ترميزات SOFTECH', 'SOFTECH codes'),
    'summary': T(
        'SOFTECH يخزن نوع العميل (قناة البيع) وتصنيف الصنف كأكواد أرقام. هذه الشاشة تقول للنظام معنى كل كود: '
        'أي قناة تعاقد، وأي قناة لها أولوية في المتابعات، وأي تصنيف «دواء»، وأي تصنيف مستبعد من التخطيط. '
        'أولوية المتابعات، وبدل الروشتة (التعاقد)، ونوع العميل المزمن، ومتابعات إعادة الصرف، والمشتريات كلها تقرأ هذا الجدول. '
        'الأسماء تأتي من SOFTECH وتتحدث مع المزامنة. الشاشة لا تكتب في SOFTECH أبدًا، وكل تعديل يُسجّل في سجل المراجعة. '
        'للمدير فقط.',
        'SOFTECH stores the customer type (sales channel) and the item category as number codes. This screen tells the '
        'system what each code means: which channel is a contract, which channel comes first in follow-ups, which category '
        'is "medicine", and which category is left out of planning. Follow-up priority, prescription replacement (contract), '
        'the chronic customer type, refill follow-ups and purchasing all read this table. The names come from SOFTECH and '
        'refresh with the sync. The screen never writes to SOFTECH, and every change is logged in the audit log. Admin only.'),
    'journeys': [
        {'key': 'classify_new_code', 'shell': 'desktop', 'roles': ['admin'],
         'title': T('تصنيف كود جديد من SOFTECH', 'Classifying a new SOFTECH code'),
         'summary': T('من تنبيه «كود جديد» إلى تحديد معناه.', 'From the "new code" alert to setting its meaning.'),
         'steps': [
            {'screen': 'code_maps.main', 'target': 'code-maps-main-tabs', 'perm': 'settings',
             'label': T('قنوات البيع · تصنيف الأصناف', 'Sales channels · Item categories'),
             'text': T('افتح التبويب الذي ذكره التنبيه: قناة بيع جديدة أو تصنيف صنف جديد.',
                       'Open the tab the alert named: a new sales channel or a new item category.')},
            {'screen': 'code_maps.main', 'target': 'code-maps-main-table', 'perm': 'settings',
             'label': T('غير مصنف', 'Unclassified'),
             'text': T('الكود الجديد في أول الجدول بشارة «غير مصنف». حتى تصنّفه لا يُحسب تعاقدًا ولا أولوية ولا دواء ولا مستبعدًا.',
                       'The new code sits at the top with an "Unclassified" badge. Until classified it counts as no contract, priority, medicine or exclusion.')},
            {'screen': 'code_maps.main', 'target': 'code-maps-main-group', 'perm': 'settings',
             'label': T('المجموعة', 'Group'),
             'text': T('اختر المجموعة وعلّم الخانات. كل تغيير يُحفظ فورًا ويُسجّل، والرفض يظهر تحت السطر.',
                       'Pick the group and tick the boxes. Each change saves at once and is logged; a refusal shows under the row.')},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في ترميزات SOFTECH', 'A tour of SOFTECH codes'),
            'summary': T('أين تُضبط معاني أكواد القنوات والتصنيفات، وما الذي يقرأها.',
                         'Where the channel and category code meanings are set, and what reads them.'),
            'roles': ['admin'],
            'steps': [
                {'target': 'nav-code-maps', 'nav': '/code-maps',
                 'text': T('«الإدارة» ← «ترميزات SOFTECH».', '"Administration" → "SOFTECH codes".'),
                 'more': T('الشاشة دي بتقول للنظام معنى كل كود نوع عميل وكل كود تصنيف صنف جاي من SOFTECH.\n'
                           '• المتابعات وبدل الروشتة والمزمن والمشتريات بتقرأ منها، والشاشة لا تكتب في SOFTECH.',
                           'This screen tells the system what every SOFTECH customer-type code and item-category code means.\n'
                           '• Follow-ups, prescription replacement, chronic and purchasing read it; the screen never writes to SOFTECH.')},
                {'target': 'code-maps-main-tabs', 'route': '/code-maps',
                 'text': T('تبويبان: قنوات البيع وتصنيف الأصناف.', 'Two tabs: sales channels and item categories.'),
                 'more': T('عدد الأكواد «غير مصنف» يظهر بجانب اسم التبويب لو فيه أكواد جديدة من SOFTECH لسه محدش صنّفها.\n'
                           '• الكود غير المصنف لا يُحسب شيئًا لحد ما تصنّفه.',
                           'The number of «Unclassified» codes shows beside the tab name when SOFTECH added codes nobody has classified yet.\n'
                           '• An unclassified code counts as nothing until you classify it.')},
                {'target': 'code-maps-main-group', 'route': '/code-maps',
                 'text': T('غيّر المجموعة أو الخانات في السطر؛ الحفظ فوري ويُسجّل.', 'Change the group or the boxes in the row; it saves at once and is logged.'),
                 'more': T('التعديل يوصل لكل الشاشات فورًا على السيرفر اللي عدّلت منه، وخلال 10 دقائق على أي سيرفر تاني.\n'
                           '• لو السيرفر رفض (مثلًا إلغاء آخر تصنيف «دواء») الرسالة تظهر تحت السطر.',
                           'A change reaches every screen at once on the server you edited from, and within 10 minutes elsewhere.\n'
                           '• If the server refuses (say, unticking the last "medicine" category) the message shows under the row.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'code_maps.main',
        'routes': ['/code-maps'],
        'title': T('ترميزات SOFTECH', 'SOFTECH codes'),
        'summary': T('معنى كل كود قناة بيع وكل كود تصنيف صنف من SOFTECH، يُعدّل في السطر نفسه.',
                     'The meaning of every SOFTECH sales-channel code and item-category code, edited in the row itself.'),
        'audience': T('المدير فقط (صلاحية الإعدادات: عرض للقراءة، تعديل للحفظ).',
                      'Admin only (Settings permission: view to read, edit to save).'),
        'tabs': [
            {'key': 'channels', 'title': T('قنوات البيع', 'Sales channels'),
             'body': T('كل كود نوع عميل في SOFTECH. «الاسم في SOFTECH» يأتي من SOFTECH ويتحدث مع المزامنة. '
                       '«المجموعة» معنى القناة عندنا (نقدي، توصيل، تعاقد، تأمين…). «بيع تعاقد» يعني أن بيع هذه القناة تعاقد: '
                       'بدل الروشتة ونوع العميل المزمن يقرآنه. «أولوية المتابعة» من 1 (الأعلى) إلى 4، أو «—» بلا أولوية؛ '
                       '1 و2 هما القنوات المفضّلة التي تتقدم في قائمة المتابعات. «بند KPI» للعرض فقط ولا يُعدّل هنا '
                       '(يبقى في إعدادات KPI حتى لا تتغير أرقام الأداء من هذه الشاشة). «مبيعات 90 يوم» عدد فواتير البيع '
                       'بهذه القناة في آخر 90 يومًا.',
                       'Every SOFTECH customer-type code. "SOFTECH name" comes from SOFTECH and refreshes with the sync. '
                       '"Group" is what the channel means to us (cash, delivery, contract, insurance…). "Contract sale" means '
                       'this channel\'s sales are contract sales: prescription replacement and the chronic customer type read it. '
                       '"Follow-up priority" runs from 1 (highest) to 4, or "—" for none; 1 and 2 are the favoured channels that '
                       'move up the follow-up list. "KPI bucket" is shown only and is not edited here (it stays in the KPI '
                       'settings so performance figures never move from this screen). "Sales 90 days" is the number of sale '
                       'invoices on this channel in the last 90 days.')},
            {'key': 'item-types', 'title': T('تصنيف الأصناف', 'Item categories'),
             'body': T('كل كود تصنيف صنف في SOFTECH. «المجموعة» معنى التصنيف (دواء، تجميل، بيطري، هدايا عملاء…). '
                       '«دواء» يحدد الأصناف التي تدخل متابعات إعادة الصرف والأمراض المزمنة وجرد الأدوية؛ يجب أن يبقى '
                       'تصنيف واحد على الأقل «دواء»، والشاشة ترفض إلغاء آخر واحد. «مستبعد من التخطيط» يُخرج أصناف التصنيف '
                       'من حساب معدلات البيع وطلبات الشراء (مثل هدايا العملاء). «عدد الأصناف» الأصناف النشطة بهذا التصنيف.',
                       'Every SOFTECH item-category code. "Group" is what the category means (medicine, cosmetics, veterinary, '
                       'client gifts…). "Medicine" decides which items enter refill and chronic follow-ups and the medicine '
                       'stock checks; at least one category must stay "medicine", and the screen refuses to untick the last '
                       'one. "Excluded from planning" leaves the category\'s items out of sales rates and purchase orders '
                       '(like client gifts). "Items" is the number of active items in the category.')},
        ],
        'steps': [
            T('اختر التبويب، ثم غيّر المجموعة أو الخانة في السطر نفسه. الحفظ فوري بلا زر حفظ، و«جارٍ الحفظ…» يظهر في السطر.',
              'Pick the tab, then change the group or a box in the row itself. It saves at once with no save button, and "Saving…" shows in the row.'),
            T('لو رفض السيرفر التغيير تظهر رسالته بالعربي تحت السطر ويرجع الاختيار لقيمته المحفوظة.',
              'If the server refuses a change, its message shows under the row and the choice goes back to its saved value.'),
        ],
        'tips': [
            T('«غير مصنف» يعني كودًا جديدًا أضافه SOFTECH ولم يصنّفه أحد بعد. يظهر في أول الجدول، ويصل للمدير تنبيه مرة واحدة. '
              'حتى تصنّفه لا يُحسب شيئًا: ليس تعاقدًا، ولا قناة مفضّلة، ولا دواء، ولا مستبعدًا من التخطيط.',
              '"Unclassified" means a new code SOFTECH added that nobody has classified yet. It shows at the top of the table, '
              'and admins get one alert. Until classified it counts as nothing: not contract, not favoured, not medicine, not '
              'excluded from planning.'),
            T('التعديل يصل لكل الشاشات فورًا على السيرفر الذي عدّلت منه، وخلال 10 دقائق على أي سيرفر آخر.',
              'A change reaches every screen at once on the server you edited from, and within 10 minutes elsewhere.'),
            T('كل تعديل يُسجّل في سجل المراجعة بالقيمة قبل وبعد ومن عدّل. تغيير لا يغيّر شيئًا لا يُسجّل.',
              'Every change is logged in the audit log with the value before and after and who made it. A change that changes nothing is not logged.'),
            T('أسماء SOFTECH وبنود KPI لا تُعدّل هنا. الشاشة لا تكتب في SOFTECH.',
              'SOFTECH names and KPI buckets are not edited here. The screen never writes to SOFTECH.'),
            T('الجدولان يترتبان بالضغط على عنوان العمود، والأكواد «غير مصنف» تبقى في الأعلى.',
              'Both tables sort by clicking a column header, and «Unclassified» codes stay on top.'),
        ],
        'related': ['admin.sync'],
        'tour': [
            {'target': 'code-maps-main-tabs', 'label': T('قنوات البيع · تصنيف الأصناف', 'Sales channels · Item categories'),
             'text': T('تبويبان: أكواد أنواع العملاء وأكواد تصنيف الأصناف من SOFTECH.',
                       'Two tabs: the SOFTECH customer-type codes and item-category codes.')},
            {'target': 'code-maps-main-table', 'label': T('الجدول', 'Table'),
             'text': T('كود في كل سطر. «غير مصنف» في الأعلى = كود جديد لا يُحسب شيئًا حتى تصنّفه.',
                       'One code per row. «Unclassified» on top = a new code that counts as nothing until classified.')},
            {'target': 'code-maps-main-group', 'label': T('المجموعة', 'Group'),
             'text': T('معنى الكود عندنا. التغيير يُحفظ فورًا ويُسجّل، ويصل لكل الشاشات خلال 10 دقائق على الأكثر.',
                       'What the code means to us. A change saves at once, is logged, and reaches every screen within 10 minutes at most.'),
             'warn': T('المتابعات والتعاقد والمشتريات تقرأ هذا المعنى — غيّره عن قصد.',
                       'Follow-ups, contracts and purchasing read this meaning — change it on purpose.')},
            {'target': 'code-maps-main-medicine', 'label': T('دواء', 'Medicine'),
             'text': T('أصناف «دواء» تدخل متابعات إعادة الصرف والمزمن. يجب أن يبقى تصنيف واحد على الأقل «دواء».',
                       '"Medicine" items enter refill and chronic follow-ups. At least one category must stay "medicine".'),
             'open_hint': _ITEMS_TAB},
            {'target': 'code-maps-main-kpi', 'label': T('بند KPI', 'KPI bucket'),
             'text': T('للعرض فقط. بنود KPI لا تُعدّل من هنا حتى لا تتغير أرقام الأداء.',
                       'Shown only. KPI buckets are not edited here, so performance figures never move.')},
        ],
        'updated': '2026-11-13',
    },
]
