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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
    },
    {
        'key': 'tasks.mobile',
        'routes': ['/m/tasks', '/m/tasks/:id'],
        'title': T('المهام (موبايل)', 'Tasks (mobile)'),
        'summary': T('ما المطلوب منك الآن: قائمة المهام بشرائح الحالة، وداخل المهمة الوصف وقائمة التحقق و«إنهاء المهمة» والمحادثة. إنشاء المهام من الكمبيوتر.',
                     'What you need to do now: the task list with status chips, and inside a task the description, checklist, "Complete task" and the chat. Tasks are created on the desktop.'),
        'audience': T('العاملون في الفروع.', 'Branch staff.'),
        'steps': [T('افتح المهمة، نفّذ قائمة التحقق، ثم «إنهاء المهمة».', 'Open the task, work through the checklist, then "Complete task".')],
        'updated': '2026-10-10',
    },
]
