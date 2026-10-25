from . import T

MODULE = {
    'key': 'tasks', 'group': 'operations', 'icon': '✅',
    'title': T('المهام التشغيلية', 'Operational tasks'),
    'summary': T(
        'إسناد ومتابعة أعمال الفروع اليومية (جرد، استلام، تحويل، توصيل، نقص، مشتريات، صيانة، اجتماع، تدريب، تدقيق، عملاء…): '
        'لكل مهمة مسؤول وفريق وموعد نهائي وأولوية، وقائمة أعمال (Checklist)، وتعليقات ومرفقات وسجل أحداث. '
        'المهام المتكررة تُنشأ تلقائياً من «الجداول التلقائية» (يومي/أسبوعي/شهري).',
        'Assign and follow the branches\' daily work (count, receiving, transfer, delivery, shortage, purchasing, maintenance, meeting, '
        'training, audit, customers…): each task has an owner, a team, a deadline and a priority, a checklist, comments, attachments '
        'and an event log. Recurring tasks are created automatically from "Schedules" (daily/weekly/monthly).'),
    'workflows': [{
        'title': T('مراحل المهمة', 'Task stages'),
        'model': 'tasks.OperationalTask', 'field': 'status',
        'states': [
            {'key': 'open', 'label': T('مفتوحة', 'Open'), 'desc': T('أُنشئت ولم يبدأ العمل.', 'Created; work not started.'), 'next': ['in_progress', 'on_hold', 'completed', 'cancelled']},
            {'key': 'in_progress', 'label': T('قيد التنفيذ', 'In progress'), 'desc': T('المسؤول يعمل عليها.', 'The owner is working on it.'), 'next': ['on_hold', 'completed', 'cancelled']},
            {'key': 'on_hold', 'label': T('متوقفة', 'On hold'), 'desc': T('متوقفة لسبب (اكتبه في التعليقات).', 'Paused for a reason (write it in the comments).'), 'next': ['in_progress', 'cancelled']},
            {'key': 'completed', 'label': T('مكتملة', 'Completed'), 'desc': T('أُغلقت بملاحظات إغلاق. يمكن «إعادة فتح».', 'Closed with closing notes. Can be reopened.'), 'next': ['open']},
            {'key': 'cancelled', 'label': T('ملغاة', 'Cancelled'), 'desc': T('لم تعد مطلوبة.', 'No longer needed.')},
        ],
    }],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول المهام التشغيلية', 'A tour of the operational tasks module'),
            'summary': T('إزاي تسند مهمة وتتابعها لحد ما تتقفل، وإزاي تشوف الصورة العامة في لوحة التحكم وتخلّي المهام المتكررة تتعمل لوحدها بالجداول التلقائية.',
                         'How to assign a task and follow it until it is closed, how to see the big picture on the dashboard, and how to let recurring tasks create themselves with automatic schedules.'),
            'roles': ['admin', 'call_center', 'pharmacist', 'supervisor'],
            'steps': [
                {'target': 'nav-tasks', 'nav': '/tasks',
                 'text': T('«العمليات» ← «المهام التشغيلية».', '"Operations" → "Operational tasks".'),
                 'more': T('هنا كل الشغل المطلوب من الفروع والفريق: جرد، استلام، صيانة، تدريب، متابعة عملاء…\n'
                           '• كل مهمة ليها مسؤول وموعد نهائي وأولوية.\n'
                           '• الموديول فيه 3 شاشات: قائمة المهام، لوحة التحكم، والجداول التلقائية.',
                           'This holds all the work asked of branches and the team: counts, receiving, maintenance, training, customer follow-up…\n'
                           '• Every task has an owner, a deadline and a priority.\n'
                           '• The module has 3 screens: the task list, the dashboard, and automatic schedules.')},
                {'target': 'tasks-list-new', 'route': '/tasks',
                 'text': T('«+ مهمة جديدة» لإسناد شغل لحد.', '"+ New task" to assign work to someone.'),
                 'more': T('بيفتح نموذج: «العنوان» (مطلوب)، النوع، الأولوية، الفرع، الموعد النهائي، «تعيين إلى»، والوصف.\n'
                           '• بعد الإنشاء بتتنقل على طول لصفحة المهمة عشان تضيف قائمة الأعمال.',
                           'Opens a form: "Title" (required), type, priority, branch, deadline, "Assign to" and description.\n'
                           '• After creating it you are taken straight to the task page to add its checklist.')},
                {'target': 'tasks-list-views', 'route': '/tasks',
                 'text': T('ثلاث طرق عرض: «≡ قائمة»، «⊟ كانبان»، «👤 مهامي».', 'Three views: "≡ List", "⊟ Kanban", "👤 My tasks".'),
                 'more': T('• «قائمة»: جدول بكل المهام وعلامة «متأخر».\n'
                           '• «كانبان»: أعمدة بالحالة تشوف فيها الشغل ماشي فين.\n'
                           '• «مهامي»: المسندة ليك بس — ابدأ يومك منها.',
                           '• "List": a table of all tasks with an "overdue" mark.\n'
                           '• "Kanban": columns by status to see where work stands.\n'
                           '• "My tasks": only those assigned to you — start your day here.')},
                {'target': 'tasks-list-filters', 'route': '/tasks',
                 'text': T('فلتر بالحالة والأولوية والنوع والفرع، و«متأخرة فقط».', 'Filter by status, priority, type, branch and "Overdue only".'),
                 'more': T('الفلاتر بتشتغل مع بعض؛ مثلاً فرع معيّن + «متأخرة فقط» يوريك اللي محتاج تدخّل فوراً.\n'
                           '• «مسح الفلاتر» بيرجّع كل المهام.',
                           'Filters combine; for example one branch + "Overdue only" shows what needs action right now.\n'
                           '• "Clear filters" brings every task back.')},
                {'target': 'tasks-list-content', 'route': '/tasks', 'wait': '/tasks/:id',
                 'text': T('افتح أي مهمة — الجولة هتكمّل جوّاها. لو مفيش مهام اضغط «إنهاء».',
                           'Open any task — the tour continues inside it. If there are none, press "End".'),
                 'more': T('اضغط على صف المهمة (أو الكارت في الكانبان) يفتح صفحتها.\n'
                           '• هناك بتحدّث الحالة، تعلّم قائمة الأعمال، وتكتب تحديثاتك.',
                           'Click a task row (or its Kanban card) to open its page.\n'
                           '• There you update the status, tick the checklist and post updates.')},
                {'target': 'tasks-detail-details', 'route': '/tasks/:id',
                 'text': T('«تفاصيل المهمة»: الحالة، الأولوية، النوع، الفرع، المسؤول والموعد.', '"Task details": status, priority, type, branch, owner and deadline.'),
                 'more': T('دي البيانات الأساسية للمهمة.\n'
                           '• عشان تغيّر أي حاجة منها (زي تخليها «قيد التنفيذ» أو تأجل الموعد) اضغط «✎ تعديل» فوق، وبعدين «حفظ».',
                           'These are the task\'s main facts.\n'
                           '• To change any of them (like setting it "In progress" or moving the deadline) press "✎ Edit" at the top, then "Save".')},
                {'target': 'tasks-detail-checklist', 'route': '/tasks/:id',
                 'text': T('«قائمة الأعمال»: البنود المطلوبة ونسبة الإنجاز.', '"Checklist": the required items and the progress.'),
                 'more': T('علّم البند لما تخلصه، والنسبة فوق بتتحدّث.\n'
                           '• اكتب بند جديد في «أضف عنصراً…» واضغط Enter، و«✕» يشيل بند.',
                           'Tick an item when you finish it and the progress at the top updates.\n'
                           '• Type a new item in "Add an item…" and press Enter; "✕" removes an item.')},
                {'target': 'tasks-detail-comments', 'route': '/tasks/:id',
                 'text': T('«التعليقات والنشاط»: تحديثاتك وتحديثات الفريق.', '"Comments & activity": your updates and the team\'s.'),
                 'more': T('اكتب إيه اللي اتعمل أو إيه اللي موقفك، وابعته بالزر أو Ctrl+Enter.\n'
                           '• تغييرات النظام (زي تغيير الحالة) بتظهر هنا كسطور رمادي، فتعرف مين عمل إيه وإمتى.',
                           'Write what was done or what is blocking you, and send it with the button or Ctrl+Enter.\n'
                           '• System changes (like a status change) appear here as grey lines, so you know who did what and when.')},
                {'target': 'tasks-detail-close', 'route': '/tasks/:id',
                 'text': T('«✓ إغلاق المهمة» لما الشغل يخلص.', '"✓ Close task" when the work is done.'),
                 'more': T('بيطلب تأكيد مع «ملاحظات الإغلاق» (اختيارية)، وبعد «تأكيد الإغلاق» المهمة تبقى «مكتملة».\n'
                           '• لو طلع فيها شغل تاني، «↩ إعادة فتح» بيرجّعها مفتوحة.',
                           'It asks for confirmation with optional "Closing notes"; after "Confirm close" the task becomes "Completed".\n'
                           '• If more work turns up, "↩ Reopen" makes it open again.')},
                {'target': 'tasks-dashboard-kpis', 'route': '/tasks/dashboard',
                 'text': T('لوحة التحكم (زر «📊 لوحة التحكم» في القائمة): الأرقام الأساسية.', 'The dashboard ("📊 Dashboard" button on the list): the key figures.'),
                 'more': T('للمدير والمشرف: «إجمالي المهام»، «نشطة»، «متأخرة»، و«معدل الإتمام (30 يوم)».\n'
                           '• اضغط أي كارت يفتح قائمة المهام متفلترة عليه.',
                           'For managers and supervisors: "Total tasks", "Active", "Overdue" and "Completion rate (30 days)".\n'
                           '• Click any card to open the task list filtered on it.')},
                {'target': 'tasks-dashboard-due-soon', 'route': '/tasks/dashboard',
                 'text': T('«المهام المستحقة قريباً» — اللي لازم تخلص الأسبوع ده.', '"Due soon" — what must finish this week.'),
                 'more': T('اضغط مهمة تفتحها على طول وتتابع مع المسؤول قبل ما تتأخر.\n'
                           '• «عرض الكل» بيفتح المهام المتأخرة.',
                           'Click a task to open it and follow up with the owner before it runs late.\n'
                           '• "View all" opens the overdue tasks.')},
                {'target': 'tasks-schedules-header', 'route': '/tasks/schedules',
                 'text': T('«الجداول التلقائية» (زر «⏱ إدارة الجداول»): مهام بتتعمل لوحدها.', '"Automatic schedules" ("⏱ Manage schedules" button): tasks that create themselves.'),
                 'more': T('للشغل اللي بيتكرر زي جرد يومي أو تدقيق أسبوعي: بتعرّفه مرة واحدة، والنظام بينشئ المهمة في معادها.\n'
                           '• المهام المولَّدة بتظهر في قائمة المهام زي أي مهمة.',
                           'For repeating work like a daily count or a weekly audit: define it once and the system creates the task on time.\n'
                           '• Generated tasks show in the task list like any other task.')},
                {'target': 'tasks-schedules-new', 'route': '/tasks/schedules',
                 'text': T('«+ جدول جديد» لتعريف مهمة متكررة.', '"+ New schedule" to define a recurring task.'),
                 'more': T('بتكتب اسم الجدول وقالب العنوان (ينفع فيه {date} و{branch})، والنوع والأولوية والفرع والمسؤول، والتكرار (يومي/أسبوعي/شهري).\n'
                           '• بعد «حفظ» تقدر تضغط «تشغيل» تجرّبه وتشوف المهمة اتعملت.',
                           'You enter the schedule name and a title template (it can use {date} and {branch}), type, priority, branch, owner and frequency (daily/weekly/monthly).\n'
                           '• After "Save" you can press "Run" to test it and see the task created.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'tasks.list',
        'routes': ['/tasks'],
        'title': T('إدارة المهام التشغيلية', 'Operational tasks'),
        'summary': T('كل المهام بثلاث طرق عرض: قائمة، كانبان حسب الحالة، ومهامي. مع إنشاء مهمة جديدة والفلترة بالحالة والأولوية والنوع والفرع والمتأخر.',
                     'All tasks in three views: list, Kanban by status, and my tasks. Create a task and filter by status, priority, type, branch and overdue.'),
        'audience': T('المديرون والمشرفون والصيادلة والكول سنتر.', 'Managers, supervisors, pharmacists and the call center.'),
        'tabs': [
            {'key': 'list', 'title': T('≡ قائمة', '≡ List'), 'body': T('جدول المهام برقمها وحالتها والمسؤول والموعد — مع علامة «متأخر».', 'Task table with number, status, owner and deadline — with an "overdue" mark.')},
            {'key': 'kanban', 'title': T('⊟ كانبان', '⊟ Kanban'), 'body': T('أعمدة حسب الحالة لترى سير العمل بنظرة.', 'Columns by status to see the flow at a glance.')},
            {'key': 'mine', 'title': T('👤 مهامي', '👤 My tasks'), 'body': T('المهام المسندة لك فقط — ابدأ يومك منها.', 'Only the tasks assigned to you — start your day here.')},
        ],
        'steps': [
            T('«مهمة جديدة»: العنوان (مطلوب)، النوع، الأولوية، الفرع، الموعد النهائي، تعيين إلى، والوصف.', '"New task": title (required), type, priority, branch, deadline, assignee and description.'),
            T('اضغط مهمة لفتح تفاصيلها.', 'Click a task to open it.'),
            T('«لوحة التحكم» لنظرة عامة على الأداء.', '"Dashboard" for an overview of performance.'),
        ],
        'related': ['tasks.detail', 'tasks.dashboard', 'tasks.schedules'],
        'tour': [
            {'target': 'tasks-list-new', 'text': T('«+ مهمة جديدة».',
                                              '"+ New task".'),
             'more': T('بيفتح نموذج مهمة: «العنوان» (مطلوب)، النوع، الأولوية، الفرع، الموعد النهائي، «تعيين إلى»، والوصف.\n'
                       '• بعد الإنشاء بتتنقل لصفحة المهمة الجديدة على طول.\n'
                       '• اختار مسؤول وموعد واضح — المهمة من غير موعد عمرها ما هتتعلّم «متأخرة».',
                       'Opens a task form: "Title" (required), type, priority, branch, deadline, "Assign to" and description.\n'
                       '• After creating it you go straight to the new task\'s page.\n'
                       '• Pick a clear owner and deadline — a task with no deadline can never be flagged "overdue".')},
            {'target': 'tasks-list-views', 'text': T('العرض: قائمة، كانبان، أو «مهامي» بس.',
                                              'View: list, kanban, or only "My tasks".'),
             'more': T('• «≡ قائمة»: جدول المهام بالرقم والحالة والمسؤول والموعد.\n'
                       '• «⊟ كانبان»: أعمدة حسب الحالة تشوف الشغل واقف فين.\n'
                       '• «👤 مهامي»: المسندة ليك بس.\n'
                       'جنبهم زر «📊 لوحة التحكم» للصورة العامة.',
                       '• "≡ List": the task table with number, status, owner and deadline.\n'
                       '• "⊟ Kanban": columns by status to see where work is stuck.\n'
                       '• "👤 My tasks": only those assigned to you.\n'
                       'Beside them, "📊 Dashboard" gives the big picture.')},
            {'target': 'tasks-list-search', 'text': T('ابحث في المهام.',
                                              'Search the tasks.'),
             'more': T('اكتب كلمة من عنوان المهمة أو رقمها والقائمة بتتفلتر.\n'
                       '• بيشتغل مع باقي الفلاتر اللي جنبه.',
                       'Type a word from the task title or its number and the list filters.\n'
                       '• It works together with the other filters beside it.')},
            {'target': 'tasks-list-filters', 'text': T('فلتر الحالة والأولوية والنوع والفرع، و«متأخرة فقط».',
                                              'Filter by status, priority, type, branch, and "Overdue only".'),
             'more': T('اجمع كذا فلتر مع بعض، مثلاً: فرع + أولوية «عاجلة» + «متأخرة فقط».\n'
                       '• «مسح الفلاتر» بيظهر لما يكون فيه فلتر شغال، وبيرجّع كل المهام.',
                       'Combine several filters, e.g. a branch + "Urgent" priority + "Overdue only".\n'
                       '• "Clear filters" appears when a filter is on and brings every task back.')},
            {'target': 'tasks-list-content', 'text': T('المهام — افتح أي مهمة لتحديثها.',
                                              'The tasks — open one to update it.'),
             'more': T('اضغط على مهمة تفتح صفحتها: التفاصيل، قائمة الأعمال، التعليقات والمرفقات.\n'
                       '• فوق الشاشة عدد المهام والنشطة والمتأخرة والعاجلة.\n'
                       '• لو القائمة فاضية فيه زر سريع لإنشاء مهمة.',
                       'Click a task to open its page: details, checklist, comments and attachments.\n'
                       '• The top of the screen shows the total, active, overdue and urgent counts.\n'
                       '• If the list is empty there is a quick button to create a task.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'tasks.detail',
        'routes': ['/tasks/:id'],
        'title': T('تفاصيل المهمة', 'Task details'),
        'summary': T('مهمة واحدة بكل تفاصيلها: الوصف، قائمة الأعمال، التعليقات والنشاط، المرفقات، الفريق (رئيسي/مساهم/مراجع/مراقب)، وسجل الأحداث.',
                     'One task in full: description, checklist, comments and activity, attachments, the team (owner/contributor/reviewer/watcher) and the event log.'),
        'audience': T('المسؤول عن المهمة وفريقها.', 'The task owner and team.'),
        'steps': [
            T('حدّث الحالة والأولوية والموعد من «تفاصيل المهمة» أو «تعديل».', 'Update status, priority and deadline from "Task details" or "Edit".'),
            T('علّم عناصر «قائمة الأعمال» عند إنجازها، وأضف عناصر جديدة.', 'Tick checklist items as you finish them, and add new ones.'),
            T('اكتب التحديثات في التعليقات (Ctrl+Enter) وارفع الملفات في المرفقات.', 'Post updates in comments (Ctrl+Enter) and upload files to attachments.'),
            T('«إغلاق المهمة» مع ملاحظات الإغلاق عند الانتهاء؛ «إعادة فتح» لو احتاجت عملاً إضافياً.', '"Close task" with closing notes when done; "Reopen" if more work is needed.'),
        ],
        'related': ['tasks.list'],
        'tour': [
            {'target': 'tasks-detail-header', 'text': T('رأس المهمة: رقمها وحالتها وعلامة «⚠ متأخرة» لو عدّت موعدها.',
                                              'The task header: its number, status and an "⚠ Overdue" mark if past its deadline.'),
             'more': T('«← المهام» بيرجّعك للقائمة.\n'
                       '• الأزرار على الطرف: «✓ إغلاق المهمة» (أو «↩ إعادة فتح» لو مقفولة) و«✎ تعديل».\n'
                       '• علامة «⚠ متأخرة» معناها إن الموعد النهائي عدّى والمهمة لسه مفتوحة.',
                       '"← Tasks" takes you back to the list.\n'
                       '• The buttons at the side: "✓ Close task" (or "↩ Reopen" when closed) and "✎ Edit".\n'
                       '• "⚠ Overdue" means the deadline has passed and the task is still open.')},
            {'target': 'tasks-detail-details', 'text': T('«تفاصيل المهمة»: الحالة، الأولوية، النوع، الفرع، المسؤول والموعد النهائي.',
                                              '"Task details": status, priority, type, branch, assignee and deadline.'),
             'more': T('هنا تعرف المهمة دي على مين ولإمتى.\n'
                       '• في وضع «تعديل» الخانات دي بتتحول لقوائم تختار منها.\n'
                       '• غيّر الحالة لـ«قيد التنفيذ» لما تبدأ، أو «متوقفة» واكتب السبب في التعليقات.',
                       'This tells you who owns the task and by when.\n'
                       '• In "Edit" mode these fields turn into drop-downs you choose from.\n'
                       '• Set the status to "In progress" when you start, or "On hold" and write why in the comments.')},
            {'target': 'tasks-detail-edit', 'text': T('«✎ تعديل» يخليك تغيّر العنوان والوصف والحالة والأولوية والموعد، وبعدها «حفظ».',
                                              '"✎ Edit" lets you change the title, description, status, priority and deadline, then "Save".'),
             'more': T('بيفتح الخانات للتعديل، ومكانه بيظهر «حفظ» و«إلغاء».\n'
                       '• مفيش حاجة بتتغيّر غير لما تضغط «حفظ».\n'
                       '• تقدر كمان تغيّر النوع والفرع والمسؤول — مفيد لو المهمة محتاجة تتنقل لزميل.',
                       'It opens the fields for editing, and "Save" and "Cancel" take its place.\n'
                       '• Nothing changes until you press "Save".\n'
                       '• You can also change the type, branch and owner — useful when the task must move to a colleague.')},
            {'target': 'tasks-detail-checklist', 'text': T('«قائمة الأعمال»: علّم البند لما تخلصه، وتقدر تضيف بنود جديدة.',
                                              '"Checklist": tick an item when you finish it, and add new items.'),
             'more': T('فوقها شريط فيه عدد المنجز من الإجمالي والنسبة.\n'
                       '• اكتب في «أضف عنصراً…» واضغط Enter أو الزر عشان تضيف بند.\n'
                       '• «✕» جنب البند بيشيله.',
                       'Above it a bar shows done out of total and the percentage.\n'
                       '• Type in "Add an item…" and press Enter or the button to add one.\n'
                       '• "✕" beside an item removes it.')},
            {'target': 'tasks-detail-comments', 'text': T('«التعليقات والنشاط»: اكتب تحديثك وابعته بـ Ctrl+Enter.',
                                              '"Comments & activity": write your update and send it with Ctrl+Enter.'),
             'more': T('المكان اللي الفريق بيتكلم فيه عن المهمة بدل الرسائل الجانبية.\n'
                       '• كل تعليق بيتسجّل باسم كاتبه ووقته.\n'
                       '• تغييرات النظام (زي تغيير الحالة) بتظهر في النص كسطور رمادي.',
                       'Where the team talks about the task instead of side messages.\n'
                       '• Each comment is saved with its author and time.\n'
                       '• System changes (like a status change) show in the middle as grey lines.')},
            {'target': 'tasks-detail-close', 'text': T('«✓ إغلاق المهمة» لما تخلص مع ملاحظات الإغلاق؛ والمهمة المغلقة بيظهر لها «↩ إعادة فتح» مكانه.',
                                              '"✓ Close task" when done, with closing notes; a closed task shows "↩ Reopen" in its place.'),
             'more': T('بيفتح تأكيد فيه «ملاحظات الإغلاق» (اختيارية) — اكتب فيها النتيجة باختصار.\n'
                       '• بعد «تأكيد الإغلاق» المهمة تبقى «مكتملة» وتطلع من المتأخر.\n'
                       '• «↩ إعادة فتح» بيطلب تأكيد ويرجّعها «مفتوحة».',
                       'It opens a confirmation with optional "Closing notes" — write the outcome briefly.\n'
                       '• After "Confirm close" the task becomes "Completed" and leaves the overdue list.\n'
                       '• "↩ Reopen" asks for confirmation and sets it back to "Open".')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'tasks.dashboard',
        'routes': ['/tasks/dashboard'],
        'title': T('لوحة تحكم المهام', 'Tasks dashboard'),
        'summary': T('نظرة عامة: إجمالي المهام، النشطة، المتأخرة، معدل الإتمام خلال 30 يوماً، توزيع الحالات، حسب النوع والفرع، المستحقة قريباً، آخر النشاطات، والجداول التلقائية النشطة.',
                     'Overview: total, active and overdue tasks, 30-day completion rate, status distribution, by type and branch, due soon, latest activity and active schedules.'),
        'audience': T('المديرون والمشرفون.', 'Managers and supervisors.'),
        'steps': [T('اختر الفرع، وركّز على «متأخرة» و«المستحقة قريباً».', 'Pick the branch and focus on "Overdue" and "Due soon".')],
        'related': ['tasks.list', 'tasks.schedules'],
        'tour': [
            {'target': 'tasks-dashboard-branch', 'text': T('اختار الفرع عشان الأرقام كلها تتحسب له، أو «كل الفروع».',
                                              'Choose a branch so all figures are for it, or "All branches".'),
             'more': T('كل الكروت والتوزيعات تحت بتتحسب على الفرع اللي تختاره.\n'
                       '• جنبه «← المهام» يرجّعك للقائمة و«⏱ إدارة الجداول» يفتح الجداول التلقائية.',
                       'Every card and breakdown below is calculated for the branch you choose.\n'
                       '• Beside it, "← Tasks" goes back to the list and "⏱ Manage schedules" opens automatic schedules.')},
            {'target': 'tasks-dashboard-kpis', 'text': T('الأرقام الأساسية: الإجمالي، النشطة، المتأخرة ومعدل الإتمام (30 يوم)؛ اضغط كارت يفتح قائمة المهام مفلترة.',
                                              'Key figures: total, active, overdue and 30-day completion rate; click a card to open the filtered task list.'),
             'more': T('• «متأخرة» أهم رقم: لو أكبر من صفر اضغطه وشوف مين محتاج متابعة.\n'
                       '• «معدل الإتمام (30 يوم)» بيقيس قد إيه المهام بتتقفل فعلاً.\n'
                       '• لو فيه مهام حرجة أو عاجلة بيظهر تحت الكروت زر بعددها يفتحها.',
                       '• "Overdue" is the key number: if above zero, click it and see who needs follow-up.\n'
                       '• "Completion rate (30 days)" measures how many tasks actually get closed.\n'
                       '• If there are critical or urgent tasks, a button with their count appears under the cards to open them.')},
            {'target': 'tasks-dashboard-breakdown', 'text': T('توزيع المهام حسب الحالة والنوع والفرع.',
                                              'Tasks broken down by status, type and branch.'),
             'more': T('تلات مربعات: «توزيع الحالات»، «حسب النوع»، و«حسب الفرع».\n'
                       '• منها تعرف فين الضغط: فرع عليه مهام كتير مفتوحة، أو نوع شغل دايماً بيتأخر.',
                       'Three boxes: "Status distribution", "By type" and "By branch".\n'
                       '• They show where the pressure is: a branch with many open tasks, or a kind of work that is always late.')},
            {'target': 'tasks-dashboard-due-soon', 'text': T('«المهام المستحقة قريباً»: اضغط مهمة تفتحها، و«عرض الكل» يفتح المتأخرة.',
                                              '"Due soon": click a task to open it; "View all" opens the overdue ones.'),
             'more': T('المهام اللي موعدها الأسبوع ده — تابعها قبل ما تتأخر.\n'
                       '• جنبها «آخر النشاطات» بآخر المهام اللي اتحركت.',
                       'Tasks due this week — follow them up before they run late.\n'
                       '• Beside it, "Latest activity" lists the most recently changed tasks.')},
            {'target': 'tasks-dashboard-schedules', 'text': T('«الجداول التلقائية النشطة»: «تشغيل» ينشئ مهمة دلوقتي، و«إدارة الجداول» يفتح شاشة الجداول.',
                                              '"Active automatic schedules": "Run" creates a task now; "Manage schedules" opens the schedules screen.'),
             'more': T('بيعرض أول 5 جداول نشطة.\n'
                       '• «تشغيل» بيعمل مهمة حقيقية دلوقتي من غير ما يستنى المعاد — استخدمه لو المهمة اتنست أو للتجربة.\n'
                       '• التعديل والإيقاف من شاشة «إدارة الجداول».',
                       'It shows the first 5 active schedules.\n'
                       '• "Run" creates a real task now without waiting for its time — use it if a task was missed or to test.\n'
                       '• Editing and pausing are done on the "Manage schedules" screen.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'tasks.schedules',
        'routes': ['/tasks/schedules'],
        'title': T('الجداول التلقائية (مهام متكررة)', 'Schedules (recurring tasks)'),
        'summary': T('إعداد مهام تتكرر تلقائياً (مثل: جرد يومي لفرع، تدقيق أسبوعي): النظام يُنشئ المهمة في موعدها بالقالب المحدد.',
                     'Set up tasks that repeat automatically (e.g. a daily branch count, a weekly audit): the system creates the task on time from the template.'),
        'audience': T('المديرون والمشرفون.', 'Managers and supervisors.'),
        'steps': [
            T('«جدول جديد»: اسم الجدول، قالب عنوان المهمة، النوع، الأولوية، الفرع، تعيين إلى (اختياري).', '"New schedule": name, task title template, type, priority, branch, assignee (optional).'),
            T('التكرار (يومي/أسبوعي/شهري) مع يوم الأسبوع أو الشهر، وكم يوماً مسبقاً للاستحقاق، والساعات المقدّرة.', 'Frequency (daily/weekly/monthly) with the weekday or month day, days ahead of due date, and estimated hours.'),
            T('«تشغيل» يُنشئ مهمة الآن للتجربة؛ زر الحالة يوقف الجدول أو ينشطه.', '"Run" creates a task now to test; the status toggle pauses or activates the schedule.'),
        ],
        'related': ['tasks.dashboard'],
        'tour': [
            {'target': 'tasks-schedules-header', 'text': T('دي «الجداول التلقائية»: النظام بينشئ المهام المتكررة في معادها من القالب.',
                                              'These are "Automatic schedules": the system creates recurring tasks on time from a template.'),
             'more': T('بدل ما تكتب نفس المهمة كل يوم أو كل أسبوع، عرّفها هنا مرة واحدة.\n'
                       '• المهام المولَّدة بتظهر في قائمة المهام عادي وبتتابعها زي أي مهمة.',
                       'Instead of writing the same task every day or week, define it here once.\n'
                       '• Generated tasks show in the task list and are followed like any task.')},
            {'target': 'tasks-schedules-new', 'text': T('«+ جدول جديد» يفتح نموذج جدول جديد.',
                                              '"+ New schedule" opens the new-schedule form.'),
             'more': T('النموذج بيظهر في نفس الصفحة فوق الجدول.\n'
                       '• مفيش حاجة بتتحفظ غير لما تضغط «حفظ» في آخر النموذج.',
                       'The form opens on the same page above the table.\n'
                       '• Nothing is saved until you press "Save" at the end of the form.')},
            {'target': 'tasks-schedules-form', 'text': T('بعد «+ جدول جديد» أو «تعديل»: الاسم، قالب العنوان، النوع، الأولوية، الفرع، المسؤول، التكرار والأيام، ثم «حفظ».',
                                              'After "+ New schedule" or "Edit": name, title template, type, priority, branch, assignee, frequency and days, then "Save".'),
             'more': T('• «اسم الجدول» و«قالب عنوان المهمة» مطلوبين؛ القالب ينفع فيه {date} و{branch} عشان كل مهمة تاخد التاريخ والفرع.\n'
                       '• «التكرار»: يومي، أو أسبوعي مع «يوم الأسبوع» (0 = الاثنين)، أو شهري مع «يوم الشهر».\n'
                       '• «أيام مسبقة للاستحقاق» والساعات المقدَّرة وقالب الوصف اختياريين.',
                       '• "Schedule name" and "Task title template" are required; the template can use {date} and {branch} so each task gets its date and branch.\n'
                       '• "Frequency": daily, weekly with "Day of week" (0 = Monday), or monthly with "Day of month".\n'
                       '• "Days ahead of due date", estimated hours and the description template are optional.')},
            {'target': 'tasks-schedules-active', 'text': T('في النموذج: علامة «نشط» بتشغّل الجدول أو توقفه.',
                                              'In the form: the "Active" tick turns the schedule on or pauses it.'),
             'more': T('شيل العلامة لو عايز توقف الجدول مؤقتاً من غير ما تمسحه (مثلاً فرع مقفول للتجديد).\n'
                       '• الجدول الموقوف ما بينشئش مهام، وزر «تشغيل» ما بيظهرلوش.',
                       'Untick it to pause the schedule without deleting it (e.g. a branch closed for renovation).\n'
                       '• A paused schedule creates no tasks and has no "Run" button.')},
            {'target': 'tasks-schedules-table', 'text': T('جدول الجداول: التكرار، الفرع، المسؤول، عدد المهام المولَّدة، آخر تشغيل والحالة.',
                                              'The schedules table: frequency, branch, assignee, tasks generated, last run and status.'),
             'more': T('راجع «آخر تشغيل» و«المهام المولَّدة» تتأكد إن الجدول شغال فعلاً.\n'
                       '• عمود «الحالة» بيوضح النشط من الموقوف.',
                       'Check "Last run" and "Tasks generated" to make sure the schedule is really working.\n'
                       '• The "Status" column shows active versus paused.')},
            {'target': 'tasks-schedules-actions', 'text': T('«تشغيل» ينشئ مهمة دلوقتي للتجربة (للجداول النشطة)، و«تعديل» و«حذف» للجدول.',
                                              '"Run" creates a task now as a test (active schedules only); "Edit" and "Delete" act on the schedule.'),
             'more': T('• «تشغيل» بيعمل مهمة حقيقية في القائمة — امسحها أو اقفلها لو كانت تجربة.\n'
                       '• «تعديل» بيفتح نفس النموذج بالبيانات الحالية.\n'
                       '• «حذف» بيطلب تأكيد، ولو عايز توقفه بس استخدم علامة «نشط» بدل الحذف.',
                       '• "Run" creates a real task in the list — close it if it was only a test.\n'
                       '• "Edit" opens the same form with the current data.\n'
                       '• "Delete" asks for confirmation; to just pause it, untick "Active" instead of deleting.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'tasks.mobile',
        'routes': ['/m/tasks', '/m/tasks/:id'],
        'title': T('المهام (موبايل)', 'Tasks (mobile)'),
        'summary': T('ما المطلوب منك الآن: قائمة المهام بشرائح الحالة، وداخل المهمة الوصف وقائمة التحقق و«إنهاء المهمة» والمحادثة. إنشاء المهام من الكمبيوتر.',
                     'What you need to do now: the task list with status chips, and inside a task the description, checklist, "Complete task" and the chat. Tasks are created on the desktop.'),
        'audience': T('العاملون في الفروع.', 'Branch staff.'),
        'steps': [T('افتح المهمة، نفّذ قائمة التحقق، ثم «إنهاء المهمة».', 'Open the task, work through the checklist, then "Complete task".')],
        'tour': [
            {'target': 'tasks-mobile-filters', 'text': T('اختار الحالة: «مفتوحة» أو «الكل» أو «جارية» أو «منجزة».',
                                              'Choose a status: "Open", "All", "In progress" or "Done".'),
             'more': T('الشاشة بتفتح على «مفتوحة» — يعني اللي لسه مطلوب منك.\n'
                       '• «منجزة» لو عايز ترجع لمهمة خلّصتها.',
                       'The screen opens on "Open" — what is still expected of you.\n'
                       '• "Done" if you want to look back at a finished task.')},
            {'target': 'tasks-mobile-list', 'text': T('دي مهامك بحالتها وموعد استحقاقها؛ اضغط على مهمة عشان تفتحها.',
                                              'These are your tasks with status and due date; tap a task to open it.'),
             'more': T('كل كارت فيه العنوان والحالة والأولوية و«يستحق:» بالتاريخ.\n'
                       '• إنشاء المهام بيتم من الكمبيوتر؛ هنا بتنفّذ وتقفل.',
                       'Each card shows the title, status, priority and "Due:" with the date.\n'
                       '• Tasks are created on the desktop; here you carry them out and finish them.')},
            {'target': 'tasks-mobile-info', 'text': T('بعد ما تفتح مهمة: هنا عنوانها وحالتها ووصفها وموعد الاستحقاق.',
                                              'After you open a task: its title, status, description and due date are here.'),
             'more': T('اقرا الوصف كويس قبل ما تبدأ — فيه المطلوب بالتفصيل.\n'
                       '• «→ الرجوع للمهام» فوق بيرجّعك للقائمة.',
                       'Read the description well before starting — it holds the details of what is needed.\n'
                       '• "→ Back to tasks" at the top returns to the list.')},
            {'target': 'tasks-mobile-checklist', 'text': T('«قائمة التحقق» بتوضح البنود المنجزة وغير المنجزة (لو المهمة فيها بنود).',
                                              'The "Checklist" shows done and pending items (when the task has any).'),
             'more': T('☑️ = بند متعلّم إنه خلص، و⬜ = لسه.\n'
                       '• على الموبايل القائمة للعرض بس؛ تعليم البنود بيتم من صفحة المهمة على الكمبيوتر.',
                       '☑️ = an item marked done, ⬜ = not yet.\n'
                       '• On the phone the list is view-only; ticking items is done on the task page on the desktop.')},
            {'target': 'tasks-mobile-complete', 'text': T('لما تخلص الشغل اضغط «✅ إنهاء المهمة» — مش بيظهر لو المهمة منتهية.',
                                              'When the work is finished press "✅ Complete task" — hidden if the task is already done.'),
             'more': T('بيقفل المهمة على طول (من غير ملاحظات إغلاق)، والمسؤول يشوفها مكتملة.\n'
                       '• لو عايز تسيب ملاحظة اكتبها في «💬 المحادثة» تحت قبل ما تنهي.',
                       'It closes the task straight away (without closing notes), and the manager sees it completed.\n'
                       '• To leave a note, write it in "💬 Chat" below before you finish.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
