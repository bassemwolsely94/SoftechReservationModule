from . import T

_RULES_TAB = T('افتح تبويب «📜 القواعد» — للمدير فقط.', 'Open the "📜 Rules" tab — admin only.')
_RULE_ROW = T('في «📜 القواعد» اضغط سطر أي قاعدة يفتح محررها تحته.', 'On "📜 Rules", click any rule row to open its editor under it.')
_HELD_TAB = T('افتح تبويب «🗄️ الملفات المحجوزة» — للمدير فقط.', 'Open the "🗄️ Held files" tab — admin only.')

MODULE = {
    'key': 'data_health', 'group': 'admin', 'icon': '🩺',
    'brief': T('حجم قاعدة البيانات والملفات وما تفعله قواعد الاحتفاظ والمشكلات المفتوحة في البيانات.',
               'Database and file sizes, what the retention rules do, and the open data problems.'),
    'title': T('صحة البيانات', 'Data health'),
    'summary': T(
        'شاشة واحدة تبيّن ما الذي يكبر في النظام وبأي سرعة، وماذا فعلت قواعد الاحتفاظ (الحذف المنظم للبيانات القديمة)، '
        'وأي الملفات محجوزة قبل حذفها نهائيًا، وما المشكلات المفتوحة في البيانات. القياس يؤخذ يوميًا مع الصيانة الليلية، '
        'ويمكن طلب قياس فوري. الشاشة على مستوى الشركة كلها (لا فروع)، لا تقرأ من SOFTECH ولا تكتب فيه، '
        'وبيانات العملاء فيها أعداد فقط بلا أسماء أو أرقام. المدير يرى كل التبويبات؛ المشرف والجودة يريان النمو والمشكلات فقط.',
        'One screen showing what is growing in the system and how fast, what the retention rules (the orderly removal of old '
        'data) did, which files are held before final removal, and which data problems are open. A measurement is taken daily '
        'with the nightly maintenance, and an immediate one can be requested. The screen is company-wide (no branches), never '
        'reads from or writes to SOFTECH, and customer data appears as counts only, with no names or numbers. Admin sees every '
        'tab; supervisors and quality see Growth and Problems only.'),
    'journeys': [
        {'key': 'weekly_check', 'shell': 'desktop', 'roles': ['admin'],
         'title': T('مراجعة أسبوعية لصحة البيانات', 'A weekly data health check'),
         'summary': T('من النمو إلى القواعد ثم المشكلات المفتوحة.', 'From growth to the rules, then the open problems.'),
         'steps': [
            {'screen': 'data_health.main', 'target': 'data-health-main-tiles', 'perm': 'data_health',
             'label': T('أيام حتى المستوى', 'Days to level'),
             'text': T('ابدأ بالبطاقات: الحجم الحالي وكم يومًا حتى يمتلئ القرص للمستوى المحدد بالمعدل الحالي.',
                       'Start with the tiles: the current size and how many days until the disk reaches the set level at the current rate.')},
            {'screen': 'data_health.main', 'target': 'data-health-main-tables', 'perm': 'data_health',
             'label': T('الجداول', 'Tables'),
             'text': T('رتّب بالنمو. جدول «غير مصنف» يكبر بلا قاعدة احتفاظ — بلّغ عنه.',
                       'Sort by growth. An «unclassified» table grows with no retention rule — report it.')},
            {'screen': 'data_health.main', 'target': 'data-health-main-rules', 'perm': 'data_health',
             'label': T('📜 القواعد', '📜 Rules'),
             'text': T('راجع آخر تشغيل وآخر معاينة لكل قاعدة. أي «فشل» يحتاج متابعة.',
                       'Check each rule’s last run and last preview. Any «failed» needs follow-up.'),
             'open_hint': _RULES_TAB},
            {'screen': 'data_health.main', 'target': 'data-health-main-problems', 'perm': 'data_health',
             'label': T('🧩 المشكلات', '🧩 Problems'),
             'text': T('أعداد المشكلات المفتوحة والتغير منذ القياس السابق. افتح الشاشة المرتبطة لإصلاحها.',
                       'Open problem counts and the change since the last measurement. Open the linked screen to fix them.'),
             'open_hint': T('افتح تبويب «🧩 المشكلات».', 'Open the "🧩 Problems" tab.')},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في صحة البيانات', 'A tour of data health'),
            'summary': T('ما الذي يكبر، وماذا فعلت القواعد، وما المشكلات المفتوحة.',
                         'What is growing, what the rules did, and which problems are open.'),
            'roles': ['admin', 'supervisor', 'quality_manager'],
            'steps': [
                {'target': 'nav-data-health', 'nav': '/data-health',
                 'text': T('«الإدارة» ← «صحة البيانات».', '"Administration" → "Data health".'),
                 'more': T('الشاشة دي بتوريك حجم قاعدة البيانات والملفات وبتكبر بأي سرعة، وماذا حذفت قواعد الاحتفاظ.\n'
                           '• قراءة بس: الشاشة نفسها لا تحذف ولا تصلح أي حاجة، ولا تقرأ من SOFTECH.',
                           'This screen shows the size of the database and files and how fast they grow, and what the retention rules removed.\n'
                           '• Read only: the screen itself deletes and fixes nothing, and never reads SOFTECH.')},
                {'target': 'data-health-main-tiles', 'route': '/data-health',
                 'text': T('بطاقات الحجم والأيام حتى امتلاء القرص للمستوى المحدد.', 'Size tiles and the days until the disk reaches the set level.'),
                 'more': T('التقدير محسوب من آخر 30 يومًا ويحتاج 7 أيام قياس على الأقل.\n'
                           '• لو الحجم بيصغر (بعد تنظيف) مش هيظهر تاريخ.',
                           'The estimate uses the last 30 days and needs at least 7 days of measurements.\n'
                           '• If the size is shrinking (after a cleanup) no date is shown.')},
                {'target': 'data-health-main-tables', 'route': '/data-health',
                 'text': T('أكبر الجداول ونموها. «غير مصنف» = بلا قاعدة احتفاظ.', 'The biggest tables and their growth. «Unclassified» = no retention rule.'),
                 'more': T('رتّب بعمود النمو عشان تشوف أسرع جدول بيكبر.\n'
                           '• جدول كبير «غير مصنف» يستاهل قاعدة — بلّغ مسؤول النظام.',
                           'Sort by the growth column to see the fastest-growing table.\n'
                           '• A big «unclassified» table deserves a rule — tell the system administrator.')},
                {'target': 'data-health-main-refresh', 'route': '/data-health',
                 'text': T('«تحديث الآن» يقيس فورًا بدل انتظار القياس الليلي.', '"Refresh now" measures at once instead of waiting for the nightly one.'),
                 'warn': T('قد يأخذ دقائق — استخدمه عند الحاجة.', 'It can take minutes — use it when needed.'),
                 'more': T('الضغط مرتين لا يشغّل قياسين؛ الشاشة بتتحدث لوحدها لما القياس يخلص.\n'
                           '• القياس الليلي يكفي في أغلب الأيام.',
                           'Pressing twice does not start two measurements; the screen updates by itself when it finishes.\n'
                           '• The nightly measurement is enough on most days.')},
                {'target': 'data-health-main-tabs', 'route': '/data-health',
                 'text': T('افتح «المشكلات» لترى الأعداد المفتوحة وروابط إصلاحها.', 'Open "Problems" to see the open counts and where to fix them.'),
                 'more': T('أعداد فقط بلا أسماء أو أرقام موبايل، مع المسؤول والتغير منذ القياس السابق.\n'
                           '• تبويبا «القواعد» و«الملفات المحجوزة» للمدير فقط.',
                           'Counts only, no names or mobile numbers, with the owner and the change since the previous measurement.\n'
                           '• The "Rules" and "Held files" tabs are admin only.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'data_health.main',
        'routes': ['/data-health'],
        'title': T('صحة البيانات', 'Data health'),
        'summary': T('النمو، وقواعد الاحتفاظ، والملفات المحجوزة، والمشكلات المفتوحة في البيانات.',
                     'Growth, retention rules, held files and the open data problems.'),
        'audience': T('المدير: كل التبويبات. المشرف والجودة: النمو والمشكلات و«تحديث الآن» فقط. لا أحد غيرهم.',
                      'Admin: every tab. Supervisors and quality: Growth, Problems and "Refresh now" only. Nobody else.'),
        'tabs': [
            {'key': 'growth', 'title': T('📈 النمو', '📈 Growth'),
             'body': T('حجم قاعدة البيانات والملفات المرفوعة الآن وعبر الأيام، والمساحة الفارغة التقديرية داخل الجداول، '
                       'وعدد الأيام حتى يصل القرص للمستوى المحدد بمعدل آخر 30 يومًا. التقدير يحتاج 7 أيام قياس على الأقل، '
                       'ولا يظهر تاريخ عندما يصغر الحجم. تحتها الجداول الأكبر ونموها (الجدول بلا قاعدة يظهر «غير مصنف»)، '
                       'وأنواع الملفات والمجلدات، وما حذفته القواعد في آخر 30 يومًا، وعدد الملفات المسترجعة، والأيام التي لم تكتمل فيها الصيانة اليومية.',
                       'The size of the database and uploaded files now and over time, the estimated empty space inside tables, and '
                       'the days until the disk reaches the set level at the last 30 days’ rate. The estimate needs at least 7 days '
                       'of measurements, and shows no date when the size is shrinking. Below: the biggest tables and their growth (a '
                       'table with no rule shows «unclassified»), file types and folders, what the rules removed in the last 30 days, '
                       'how many files were restored, and the days the daily maintenance did not complete.')},
            {'key': 'rules', 'title': T('📜 القواعد', '📜 Rules'),
             'body': T('كل قاعدة احتفاظ بوضعها (متوقفة / معاينة فقط / تعمل) ومدتها وآخر تشغيل وآخر معاينة. اضغط القاعدة '
                       'لتعدّلها: المدة لا تقل عن الحد الأدنى، والتشغيل يحتاج معاينة ناجحة عمرها أقل من 7 أيام، والسبب إلزامي، '
                       'وكل تعديل يُسجّل قبل وبعد في سجل المراجعة. قواعد الملفات مقفلة على المعاينة حتى الانتقال إلى السيرفر. '
                       'خطوات الصيانة اليومية القديمة تظهر للعلم ولا تُعدّل. للمدير فقط.',
                       'Every retention rule with its mode (off / preview only / on), period, last run and last preview. Click a '
                       'rule to change it: the period cannot go below the minimum, turning it on needs a successful preview under 7 '
                       'days old, a reason is required, and every change is logged before and after in the audit log. File rules '
                       'stay locked in preview until the move to the server. The older daily maintenance steps show for '
                       'information and cannot be changed. Admin only.')},
            {'key': 'held', 'title': T('🗄️ الملفات المحجوزة', '🗄️ Held files'),
             'body': T('الملفات التي نقلتها القواعد من مجلد الملفات تنتظر هنا 30 يومًا قبل حذفها نهائيًا. لكل ملف: القاعدة، '
                       'ونوع السجل ورقمه، والحجم، وتاريخ الحجز وتاريخ الحذف النهائي. «استرجاع» يعيد الملف لمكانه بعد تأكيد في '
                       'نفس السطر، ويُرفض إذا كان مكانه مشغولًا بملف آخر. الصور المصغّرة لصور الأصناف فقط، ولا تظهر أبدًا لصور '
                       'الروشتات أو المحادثات. الملفات التي حذفها أو استبدلها موظف («حذف سجل» و«استبدال ملف») يظهر معها اسم '
                       'الموظف في عمود «حذفه»، ولا تُسترجع إلى مكانها. لا يظهر مسار أي ملف. للمدير فقط.',
                       'Files the rules moved out of the media folder wait here 30 days before final removal. For each file: the '
                       'rule, the record type and number, the size, the date held and the final removal date. "Restore" puts the '
                       'file back after a confirmation in the same row, and is refused if its place is taken by another file. '
                       'Thumbnails are for item images only and never show for prescriptions or conversations. No file path is '
                       'ever shown. Files a staff member deleted or replaced ("Record deleted", "File replaced") show who did it in '
                       'the "Deleted by" column and are not restored in place. Admin only.')},
            {'key': 'problems', 'title': T('🧩 المشكلات', '🧩 Problems'),
             'body': T('أعداد المشكلات المفتوحة في البيانات من آخر قياس: أرقام موبايل مشتركة أو بصيغة غير صحيحة، عملاء بلا '
                       'مشتريات، مواد فعالة تنتظر المراجعة، متابعات وتوصيلات وحالات توريد وجرد ونقاط بيع مفتوحة أكثر من 90 يومًا. '
                       'لكل مشكلة المسؤول عنها والتغير منذ القياس السابق ورابط الشاشة التي تُصلح منها. هذه الشاشة لا تصلح ولا '
                       'تحذف شيئًا، وتعرض أعدادًا فقط بلا أسماء أو أرقام. «—» يعني أن العدد لم يُحسب في آخر قياس.',
                       'Open data problem counts from the last measurement: shared or badly formatted mobile numbers, customers with '
                       'no purchases, active ingredients awaiting review, follow-ups, deliveries, supply cases, stock counts and POS '
                       'orders open over 90 days. Each shows its owner, the change since the previous measurement and a link to the '
                       'screen where it is fixed. This screen fixes and deletes nothing, and shows counts only, no names or numbers. '
                       '"—" means the count was not computed in the last measurement.')},
        ],
        'tips': [
            T('القياس اليومي يكفي عادةً. «تحديث الآن» يقيس الجداول والملفات فورًا وقد يأخذ دقائق؛ الضغط مرتين لا يشغّل قياسين.',
              'The daily measurement is usually enough. "Refresh now" measures tables and files at once and can take minutes; pressing it twice does not start two.'),
            T('كل الجداول في الشاشة تترتب بالضغط على عنوان العمود.', 'Every table on the screen sorts by clicking a column header.'),
        ],
        'related': ['admin.sync'],
        'tour': [
            {'target': 'data-health-main-tabs', 'label': T('النمو · القواعد · الملفات · المشكلات', 'Growth · Rules · Files · Problems'),
             'text': T('أربعة تبويبات. المشرف والجودة يريان النمو والمشكلات فقط.', 'Four tabs. Supervisors and quality see Growth and Problems only.')},
            {'target': 'data-health-main-refresh', 'label': T('🔄 تحديث الآن', '🔄 Refresh now'),
             'text': T('يقيس أحجام الجداول والملفات والمشكلات الآن بدل انتظار القياس الليلي. لا يحذف شيئًا.',
                       'Measures table and file sizes and the problems now instead of waiting for the nightly one. Deletes nothing.'),
             'warn': T('قد يأخذ دقائق ويحمّل السيرفر قليلًا — استخدمه عند الحاجة.', 'It can take minutes and loads the server a little — use it when needed.')},
            {'target': 'data-health-main-tiles', 'label': T('بطاقات الحجم', 'Size tiles'),
             'text': T('قاعدة البيانات، والملفات، والمساحة الفارغة، والأيام حتى المستوى المحدد من القرص.',
                       'Database, files, empty space, and the days until the set disk level.')},
            {'target': 'data-health-main-chart', 'label': T('الحجم عبر الأيام', 'Size over time'),
             'text': T('خطان: قاعدة البيانات والملفات. يظهر بعد يومين من القياس.', 'Two lines: database and files. Shows after two days of measurements.')},
            {'target': 'data-health-main-tables', 'label': T('الجداول', 'Tables'),
             'text': T('أكبر الجداول ونموها في 30 يومًا. «غير مصنف» = لا تحذف منه أي قاعدة.',
                       'The biggest tables and their 30-day growth. «Unclassified» = no rule removes from it.')},
            {'target': 'data-health-main-measures', 'label': T('ما فعلته القواعد', 'What the rules did'),
             'text': T('ما حذفته كل قاعدة في 30 يومًا، والملفات المسترجعة، والأيام التي فاتت فيها الصيانة.',
                       'What each rule removed in 30 days, the files restored, and the days maintenance was missed.')},
            {'target': 'data-health-main-rules', 'label': T('📜 القواعد', '📜 Rules'),
             'text': T('وضع كل قاعدة ومدتها وآخر تشغيل ومعاينة. اضغط القاعدة لتعديلها.',
                       'Each rule’s mode, period, last run and preview. Click a rule to change it.'),
             'open_hint': _RULES_TAB},
            {'target': 'data-health-main-rule-preview', 'label': T('معاينة', 'Preview'),
             'text': T('يحسب ما كانت القاعدة ستحذفه الآن، ولا يحذف شيئًا. لازم قبل التشغيل.',
                       'Counts what the rule would remove now, and removes nothing. Needed before turning it on.'),
             'open_hint': _RULE_ROW},
            {'target': 'data-health-main-rule-save', 'label': T('حفظ', 'Save'),
             'text': T('يحفظ الوضع والمدة مع السبب، ويُسجّل قبل وبعد. الرفض يظهر تحت الأزرار.',
                       'Saves the mode and period with the reason, logged before and after. A refusal shows under the buttons.'),
             'warn': T('«تعمل» يعني حذفًا فعليًا في الصيانة القادمة — راجع المعاينة أولًا.',
                       '"On" means real removal in the next maintenance — check the preview first.'),
             'open_hint': _RULE_ROW},
            {'target': 'data-health-main-held', 'label': T('🗄️ الملفات المحجوزة', '🗄️ Held files'),
             'text': T('الملفات المنتظرة للحذف النهائي، بلا مسارات. الصورة المصغّرة لصور الأصناف فقط.',
                       'Files waiting for final removal, with no paths. Thumbnails for item images only.'),
             'open_hint': _HELD_TAB},
            {'target': 'data-health-main-restore', 'label': T('استرجاع', 'Restore'),
             'text': T('يعيد الملف لمكانه بعد «نعم، استرجع» في نفس السطر، ويُسجّل.',
                       'Puts the file back after "Yes, restore" in the same row, and is logged.'),
             'warn': T('يُرفض إذا كان مكان الملف مشغولًا بملف آخر.', 'Refused if the file’s place is taken by another file.'),
             'open_hint': _HELD_TAB},
            {'target': 'data-health-main-problems', 'label': T('🧩 المشكلات', '🧩 Problems'),
             'text': T('أعداد فقط مع المسؤول والتغير ورابط الشاشة التي تُصلح منها. الشاشة لا تصلح شيئًا.',
                       'Counts only, with the owner, the change and a link to the screen that fixes it. This screen fixes nothing.'),
             'open_hint': T('افتح تبويب «🧩 المشكلات».', 'Open the "🧩 Problems" tab.')},
        ],
        'updated': '2026-11-12',
    },
]
