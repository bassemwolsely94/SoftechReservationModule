from . import T

_DRAWER = T('اضغط «إضافة مستخدم» (أو ✎ تعديل على مستخدم) يفتح النموذج.', 'Press "Add user" (or ✎ Edit on a user) to open the form.')
_NEW_DRAWER = T('اضغط «إضافة مستخدم» يفتح النموذج.', 'Press "Add user" to open the form.')
_ROW = T('في عمود «إجراءات» لكل مستخدم (للمدير فقط).', 'In the "Actions" column of every user (admins only).')
_ROLE = T('اختار دور من قائمة «الأدوار» على اليمين.', 'Pick a role from the "Roles" list on the side.')
_BRANCHES = T('افتح تبويب «🏪 الفروع».', 'Open the "🏪 Branches" tab.')
_FLAGS = T('في تبويب «⚠️ الإشارات المشبوهة».', 'On the "⚠️ Suspicious flags" tab.')
_LOGS = T('افتح تبويب «📋 سجل الإجراءات».', 'Open the "📋 Action log" tab.')

MODULE = {
    'key': 'admin', 'group': 'admin', 'icon': '⚙️',
    'brief': T('المستخدمين وأدوارهم وصلاحياتهم، والإعدادات، والمزامنة مع SOFTECH.',
               'Users, their roles and permissions, settings, and the sync with SOFTECH.'),
    'title': T('الإدارة والنظام', 'Administration & system'),
    'summary': T(
        'إدارة المستخدمين وأدوارهم وفروعهم، مصفوفة الصلاحيات (ما يراه ويفعله كل دور في كل موديول) والصلاحيات الموروثة من مجموعات SOFTECH، '
        'إعدادات النظام، حالة المزامنة مع SOFTECH، وسجل المراجعة مع كشف الأنماط المشبوهة. الأدوار: مدير، مشرف، صيدلي، مندوب مبيعات، كول سنتر، مشتريات، توصيل، جودة، مشاهد فقط.',
        'Manage users, their roles and branches, the permissions matrix (what each role sees and does in each module) and permissions inherited from SOFTECH groups, '
        'system settings, the SOFTECH sync status, and the audit log with suspicious-pattern detection. Roles: admin, supervisor, pharmacist, salesperson, call center, purchasing, delivery, quality, viewer.'),
    'journeys': [
        {'key': 'onboard_staff', 'shell': 'desktop', 'roles': ['admin'],
         'title': T('تعيين موظف جديد على النظام', 'Onboarding a new staff member'),
         'summary': T('إنشاء المستخدم وربطه بـ SOFTECH، تحديد الدور والفرع والوصول، ثم مراجعة صلاحيات الدور.',
                      'Create the user and link it to SOFTECH, set the role, branch and access, then review the role\'s permissions.'),
         'steps': [
            {'screen': 'admin.users', 'target': 'admin-users-add', 'perm': 'users',
             'label': T('إضافة مستخدم', 'Add user'),
             'text': T('ابدأ من هنا: يفتح نموذج «إضافة مستخدم جديد».', 'Start here: opens the "Add new user" form.')},
            {'screen': 'admin.users', 'target': 'admin-users-softech-link', 'perm': 'users',
             'label': T('بحث في مستخدمي SOFTECH', 'Search SOFTECH users'),
             'text': T('اكتب اسمه واختاره من النتائج عشان الحساب يتربط بمستخدمه في SOFTECH.',
                       'Type the name and pick it from the results so the account links to their SOFTECH user.'),
             'warn': T('من غير ربط مايقدرش يعتمد حاجة بتتنفّذ في SOFTECH باسمه.', 'Without the link they cannot approve anything executed in SOFTECH under their name.'),
             'open_hint': _NEW_DRAWER},
            {'screen': 'admin.users', 'target': 'admin-users-password', 'perm': 'users',
             'label': T('كلمة المرور *', 'Password *'),
             'text': T('10 حروف على الأقل، مش أرقام بس، ومش شبه اسم المستخدم.', 'At least 10 characters, not digits only, and not close to the username.'),
             'open_hint': _NEW_DRAWER},
            {'screen': 'admin.users', 'target': 'admin-users-role', 'perm': 'users',
             'label': T('الدور *', 'Role *'),
             'text': T('الدور بيحدد الصلاحيات من مصفوفة الصلاحيات.', 'The role decides the permissions from the permissions matrix.'),
             'open_hint': _NEW_DRAWER},
            {'screen': 'admin.users', 'target': 'admin-users-branch', 'perm': 'users',
             'label': T('الفرع الأساسي', 'Main branch'),
             'text': T('فرع الموظف. «— المركز الرئيسي —» لموظفي الإدارة.', 'The employee\'s branch. "— Head office —" for HQ staff.'),
             'open_hint': _NEW_DRAWER},
            {'screen': 'admin.users', 'target': 'admin-users-access', 'perm': 'users',
             'label': T('صلاحيات الوصول', 'Access'),
             'text': T('كل الفروع، قنوات البيع المسموحة، عملاء كل الفروع، ورؤية رقم الهاتف. ادّي أقل وصول يكفي شغله.',
                       'All branches, allowed sales channels, all-branch customers, phone visibility. Give the least access the job needs.'),
             'open_hint': _NEW_DRAWER},
            {'screen': 'admin.users', 'target': 'admin-users-save', 'perm': 'users',
             'label': T('إنشاء المستخدم', 'Create user'),
             'text': T('يحفظ الحساب ويقدر يدخل على طول.', 'Saves the account; they can log in straight away.'),
             'open_hint': _NEW_DRAWER},
            {'screen': 'admin.permissions', 'target': 'admin-permissions-roles',
             'label': T('الأدوار', 'Roles'),
             'text': T('اختار نفس دور الموظف الجديد وراجع هيشوف إيه.', 'Pick the new employee\'s role and review what they will see.')},
            {'screen': 'admin.permissions', 'target': 'admin-permissions-matrix',
             'label': T('الوحدة × الإجراء', 'Module × action'),
             'text': T('لو محتاج تعديل علّم أو شيل الإجراء. التعديل بيسري على كل مستخدمي الدور.',
                       'Tick or untick actions if needed. A change applies to every user of the role.'),
             'open_hint': _ROLE},
            {'screen': 'admin.permissions', 'target': 'admin-permissions-save',
             'label': T('حفظ التغييرات (…)', 'Save changes (…)'),
             'text': T('مفيش حاجة بتتطبّق قبل الحفظ.', 'Nothing applies before saving.'),
             'warn': T('بيأثر فوراً على كل مستخدمي الدور، مش الموظف الجديد بس.', 'Takes effect at once for every user of the role, not only the new employee.'),
             'open_hint': T('يظهر لما يكون فيه تغيير غير محفوظ.', 'Shown when there is an unsaved change.')},
         ]},
        {'key': 'sync_check', 'shell': 'desktop', 'roles': ['admin'],
         'title': T('فحص صحة المزامنة مع SOFTECH', 'Checking the SOFTECH sync health'),
         'summary': T('تأكد إن المجدول شغال، والفروع متصلة، وآخر مزامنة نجحت — وشغّل مزامنة لو لزم.',
                      'Make sure the scheduler runs, branches are connected and the last sync succeeded — and run a sync if needed.'),
         'steps': [
            {'screen': 'admin.sync', 'target': 'admin-sync-status', 'perm': 'sync',
             'label': T('حالة المزامنة', 'Sync status'),
             'text': T('أخضر = آخر مزامنة نجحت. أحمر = فشلت، والسبب مكتوب تحتها.', 'Green = the last sync succeeded. Red = it failed, with the reason below.')},
            {'screen': 'admin.sync', 'target': 'admin-sync-scheduler', 'perm': 'sync',
             'label': T('المجدول متوقف — المهام لا تعمل', 'Scheduler stopped — jobs not running'),
             'text': T('لو ظهر، كل المهام التلقائية واقفة — بلّغ مسؤول السيرفر يشغّله.', 'If shown, every automatic job is stopped — ask the server admin to start it.'),
             'open_hint': T('بيظهر بس لما المجدول يقف — غيابه علامة كويسة.', 'Shown only when the scheduler stops — its absence is good.')},
            {'screen': 'admin.sync', 'target': 'admin-sync-branch-health', 'perm': 'sync',
             'label': T('حالة اتصال الشبكة', 'Network connection status'),
             'text': T('المركز وكل فرع: متصل، غير متصل، أو منقطع باستمرار.', 'HQ and every branch: connected, disconnected or persistently down.')},
            {'screen': 'admin.sync', 'target': 'admin-sync-probe', 'perm': 'sync',
             'label': T('🔄 فحص الآن', '🔄 Check now'),
             'text': T('يختبر الاتصال بكل نقطة دلوقتي بدل ما تستنى الفحص الدوري.', 'Tests every node\'s connection now instead of waiting for the periodic check.')},
            {'screen': 'admin.sync', 'target': 'admin-sync-now', 'perm': 'sync',
             'label': T('↻ مزامنة الآن', '↻ Sync now'),
             'text': T('يسحب آخر البيانات من SOFTECH في الخلفية. قراءة بس، مش بيكتب في SOFTECH.',
                       'Pulls the latest data from SOFTECH in the background. Read only; nothing is written to SOFTECH.')},
            {'screen': 'admin.sync', 'target': 'admin-sync-logs', 'perm': 'sync',
             'label': T('سجل المزامنة', 'Sync log'),
             'text': T('تابع العملية: الحالة، عدد السجلات والمدة لكل جدول.', 'Follow the run: status, records and duration per table.')},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول الإدارة والنظام', 'A tour of the Administration & system module'),
            'summary': T('من إضافة مستخدم وتحديد دوره، لصلاحيات كل دور، للإعدادات والفروع، ومتابعة المزامنة مع SOFTECH، لحد سجل المراجعة والإشارات المشبوهة.',
                         'From adding a user and setting their role, to each role\'s permissions, settings and branches, the SOFTECH sync, and finally the audit log and suspicious flags.'),
            'roles': ['admin'],
            'steps': [
                {'target': 'nav-users', 'nav': '/users',
                 'text': T('نبدأ من «المستخدمون» في مجموعة «الإدارة».',
                           'Start at "Users" in the "Administration" group.'),
                 'more': T('كل حاجة في النظام بتبدأ من المستخدم: دوره بيحدد صلاحياته، وفرعه بيحدد بياناته اللي بيشوفها.\n'
                           'المدير بيضيف ويعدّل هنا، والمشرف بيشوف القائمة بس.',
                           'Everything starts from the user: their role sets their permissions and their branch sets the data they see.\n'
                           'Admins add and edit here; supervisors can only view the list.')},
                {'target': 'admin-users-add', 'route': '/users',
                 'text': T('«إضافة مستخدم» لموظف جديد مربوط بحسابه في SOFTECH.',
                           '"Add user" for a new employee linked to their SOFTECH account.'),
                 'more': T('بيفتح نموذج: ابحث عن المستخدم في SOFTECH واختاره، وبعدين كلمة المرور والاسم والدور والفرع الأساسي.\n'
                           'الربط بـ SOFTECH مهم للاعتمادات اللي بتتنفذ في SOFTECH باسمه، والحساب مش بيتعمل غير بـ«إنشاء المستخدم».',
                           'It opens a form: search the user in SOFTECH and pick them, then password, name, role and main branch.\n'
                           'The SOFTECH link matters for approvals executed in SOFTECH under their name; nothing is created until "Create user".')},
                {'target': 'admin-users-actions', 'route': '/users',
                 'text': T('لكل مستخدم: تعديل، كلمة مرور، تعطيل/تفعيل، وسجل النشاط.',
                           'Per user: edit, password, deactivate/activate, and the activity log.'),
                 'more': T('لما موظف يسيب الشغل عطّل حسابه بدل ما تمسحه — تاريخه بيفضل محفوظ.\n'
                           'تغيير الدور أو الفرع أو التعطيل كله بيتسجّل في «سجل النشاط» بتاع المستخدم.',
                           'When an employee leaves, deactivate their account instead of deleting it — their history stays.\n'
                           'Role, branch and activation changes are all recorded in the user\'s "Activity log".')},
                {'target': 'nav-permissions', 'nav': '/permissions',
                 'text': T('بعدها «الصلاحيات»: إيه اللي كل دور يشوفه ويعمله.',
                           'Next, "Permissions": what each role sees and does.'),
                 'more': T('الدور اللي اخترته للمستخدم بياخد صلاحياته من هنا.\n'
                           'السيرفر بيطبّق نفس المصفوفة على كل طلب، والقائمة والأزرار بتستخبى حسبها — يعني الصلاحية هنا هي الحماية الحقيقية.',
                           'The role you gave the user takes its permissions from here.\n'
                           'The server applies the same matrix to every request, and menus and buttons hide accordingly — so permissions here are the real protection.')},
                {'target': 'admin-permissions-roles', 'route': '/permissions',
                 'text': T('اختار الدور، وعلّم الإجراءات المسموحة لكل وحدة.',
                           'Pick the role, then tick the allowed actions per module.'),
                 'more': T('بعد ما تختار الدور، الجدول بيعرض كل وحدة × إجراء (عرض، إنشاء، تعديل، حذف، اعتماد…).\n'
                           'النقطة الصفرا جنب الدور معناها إن عنده تغييرات لسه ما اتحفظتش. المدير له وصول كامل مش بيتعدّل.',
                           'Once you pick a role, the table shows each module × action (view, create, edit, delete, approve…).\n'
                           'A yellow dot next to a role means it has unsaved changes. Admins have full access that cannot be edited.')},
                {'target': 'admin-permissions-save-bar', 'route': '/permissions',
                 'text': T('مفيش حاجة بتتطبّق غير بـ«حفظ التغييرات».',
                           'Nothing applies until "Save changes".'),
                 'more': T('هنا بيظهر عدد التغييرات غير المحفوظة، و«تراجع» يرجّع كل حاجة زي ما كانت، و«حفظ التغييرات» يطبّقها.\n'
                           'الحفظ بيتسجّل باسمك في سجل نشاط المستخدمين.',
                           'Here you see the number of unsaved changes; "Undo" puts everything back and "Save changes" applies them.\n'
                           'Saving is recorded under your name in the user activity log.')},
                {'target': 'nav-erp-permissions', 'nav': '/erp-permissions',
                 'text': T('«صلاحيات Softech»: صلاحيات مشتقة من مجموعة المستخدم في SOFTECH.',
                           '"Softech permissions": permissions derived from the user\'s SOFTECH group.'),
                 'more': T('جنب المصفوفة، النظام بيشتق صلاحيات الوحدات من مجموعة المستخدم في SOFTECH، ويُعاد البناء يومياً.\n'
                           'هنا بتراجع وتعدّل طريقة الاشتقاق — من غير أي كتابة في SOFTECH نفسه.',
                           'Alongside the matrix, module permissions are derived from the user\'s SOFTECH group and rebuilt daily.\n'
                           'Here you review and adjust how they are derived — without writing anything to SOFTECH itself.')},
                {'target': 'admin-erp-permissions-rebuild', 'route': '/erp-permissions',
                 'text': T('«إعادة الاشتقاق الآن» يطبّق الاشتقاق فوراً.',
                           '"Re-derive now" applies the derivation immediately.'),
                 'more': T('استخدمه بعد ما تغيّر الربط لو مش عايز تستنى البناء اليومي.\n'
                           'بيعيد حساب صلاحيات كل مجموعة، والنتيجة بتظهر في تبويب «صلاحيات المجموعات».',
                           'Use it after changing the mapping if you do not want to wait for the daily rebuild.\n'
                           'It recalculates every group\'s permissions; the result shows in the "Group permissions" tab.')},
                {'target': 'nav-settings', 'nav': '/settings',
                 'text': T('«الإعدادات»: بيانات الصيدلية والفروع وقواعد كل موديول.',
                           '"Settings": pharmacy details, branches and each module\'s rules.'),
                 'more': T('هنا بتتظبط القواعد اللي باقي الشاشات بتشتغل بيها.\n'
                           'المدير بيعدّل، والصيدلي بيشوف «عرض فقط».',
                           'This is where the rules the other screens run on are set.\n'
                           'Admins edit; pharmacists see "View only".')},
                {'target': 'admin-settings-tabs', 'route': '/settings',
                 'text': T('أقسام الإعدادات: عام، المظهر، الفروع، الحجوزات، التحويل، الإشعارات، المزامنة، القسائم، القوائم المنسدلة.',
                           'Settings sections: General, Appearance, Branches, Reservations, Transfers, Notifications, Sync, Vouchers, Dropdowns.'),
                 'more': T('• «الفروع»: حالة كل فرع وميزاته وإحداثياته (لازمة لتحقق الحضور والاستلام).\n'
                           '• «القوائم المنسدلة»: خيارات زي قنوات الحجز.\n'
                           '• باقي الأقسام: إعدادات كل موديول، وكل إعداد بيتحفظ لوحده بزرار «حفظ» جنبه.',
                           '• "Branches": each branch\'s status, features and coordinates (needed for attendance and pickup checks).\n'
                           '• "Dropdowns": options such as reservation channels.\n'
                           '• The other sections: each module\'s settings; each setting is saved on its own with the "Save" next to it.')},
                {'target': 'nav-sync', 'nav': '/sync',
                 'text': T('«المزامنة»: البيانات اللي جاية من SOFTECH.',
                           '"Sync": the data coming from SOFTECH.'),
                 'more': T('الأصناف والمخزون والعملاء والمبيعات والمستخدمين بيتسحبوا من SOFTECH تلقائياً كل 5 دقايق.\n'
                           'لو حد اشتكى إن بيانات مش ظاهرة أو قديمة، هنا أول مكان تبص فيه.',
                           'Items, stock, customers, sales and users are pulled from SOFTECH automatically every 5 minutes.\n'
                           'If someone says data is missing or stale, this is the first place to look.')},
                {'target': 'admin-sync-status', 'route': '/sync',
                 'text': T('حالة آخر مزامنة — لو فشلت، السبب مكتوب هنا.',
                           'The last sync status — if it failed, the reason is shown here.'),
                 'more': T('أخضر «المزامنة تعمل بشكل طبيعي»، أصفر «جارٍ»، أحمر «فشلت آخر مزامنة» ومعاها رسالة الخطأ.\n'
                           'وفوق الكارت ممكن يظهر تحذير «المجدول متوقف» — وقتها المهام التلقائية كلها واقفة.',
                           'Green "Sync running normally", amber "Running", red "Last sync failed" with the error message.\n'
                           'Above the card a "Scheduler stopped" warning may show — then all automatic jobs are stopped.')},
                {'target': 'admin-sync-branch-health', 'route': '/sync',
                 'text': T('حالة اتصال المركز وكل فرع.',
                           'The connection status of head office and each branch.'),
                 'more': T('لكل نقطة: متصل، غير متصل، أو «منقطع باستمرار» بعد محاولات فاشلة متتالية.\n'
                           '«فحص الآن» يختبر الاتصال فوراً. الفرع المنقطع بياناته مش هتتحدث لحد ما يرجع.',
                           'For each node: connected, disconnected, or "persistently down" after consecutive failures.\n'
                           '"Check now" tests the connection immediately. A disconnected branch\'s data will not update until it is back.')},
                {'target': 'nav-audit', 'nav': '/audit',
                 'text': T('وأخيراً «المراجعة والأمان»: مين عمل إيه وإمتى.',
                           'Finally "Audit & security": who did what, and when.'),
                 'more': T('كل الإجراءات المهمة في الموديولات التانية بتتسجّل هنا، والنظام بيدوّر فيها على أنماط مشبوهة.\n'
                           'متاحة للمدير والمشرف ومدير الجودة.',
                           'Every important action in the other modules is recorded here, and the system scans it for suspicious patterns.\n'
                           'Available to admins, supervisors and the quality manager.')},
                {'target': 'admin-audit-tabs', 'route': '/audit',
                 'text': T('«الإشارات المشبوهة» أو «سجل الإجراءات».',
                           '"Suspicious flags" or "Action log".'),
                 'more': T('• «الإشارات المشبوهة»: إلغاءات أو تعديلات متكررة، عدم تطابق ERP، نشاط خارج الدوام — بدرجة خطورة.\n'
                           '• «سجل الإجراءات»: كل حدث بالمستخدم والكيان والوقت، واضغط على السطر تشوف التغييرات.',
                           '• "Suspicious flags": repeated cancellations or edits, ERP mismatch, after-hours activity — by severity.\n'
                           '• "Action log": every event with user, entity and time; click a row to see the changes.')},
                {'target': 'admin-audit-scan', 'route': '/audit',
                 'text': T('«🔍 فحص الآن» يدوّر على أنماط مشبوهة في آخر 24 ساعة.',
                           '"🔍 Scan now" looks for suspicious patterns in the last 24 hours.'),
                 'more': T('بعد الفحص بتظهر رسالة بعدد الإشارات الجديدة، وتظهر في القائمة تحت «مفتوح».\n'
                           'كل إشارة مفتوحة عليها «مراجعة» — راجعت، تجاهل، أو تصعيد مع ملاحظة.',
                           'After the scan a message shows the number of new flags, and they appear in the list under "Open".\n'
                           'Each open flag has "Review" — reviewed, ignore, or escalate with a note.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'admin.users',
        'routes': ['/users'],
        'title': T('إدارة المستخدمين', 'User management'),
        'summary': T('إنشاء المستخدمين وتعديلهم وتعطيلهم، وإعادة تعيين كلمة المرور، وسجل نشاط كل مستخدم (دخول، تغيير دور أو فرع أو صلاحيات).', 'Create, edit and deactivate users, reset passwords, and each user\'s activity log (logins, role, branch or permission changes).'),
        'audience': T('المدير (والمشرف للعرض).', 'Admins (supervisors can view).'),
        'steps': [
            T('«إضافة مستخدم»: ابحث عن اسم المستخدم في SOFTECH ليُربط به، ثم كلمة المرور والاسم والهاتف وكود الموارد البشرية.', '"Add user": search the SOFTECH username to link, then password, name, phone and HR code.'),
            T('حدد الدور والفرع الأساسي، وصلاحيات الوصول: وصول لكل الفروع، قنوات البيع المسموح بها في نقطة البيع (فارغ = كلها)، رؤية عملاء كل الفروع، رؤية رقم هاتف العميل.', 'Set the role and main branch, and access: all branches, allowed POS sales channels (empty = all), see customers of all branches, see customer phone numbers.'),
            T('«الحساب نشط» لإيقاف أو تفعيل الدخول بدون حذف المستخدم.', '"Account active" stops or allows login without deleting the user.'),
        ],
        'tips': [T('ربط المستخدم بمستخدم SOFTECH ضروري للاعتمادات التي تُنفَّذ في SOFTECH باسمه.', 'Linking the user to a SOFTECH user is required for approvals executed in SOFTECH under their name.'),
                 T('كلمة المرور 10 أحرف على الأقل، وتُرفض إن كانت شائعة (مثل password123) أو أرقاماً فقط أو قريبة من اسم المستخدم — عند الإنشاء وإعادة التعيين وتغيير كلمة المرور.',
                   'Passwords need at least 10 characters and are refused if common (like password123), digits only, or close to the username — on create, reset and password change.')],
        'related': ['admin.permissions', 'admin.erp_permissions'],
        'tour': [
            {'target': 'admin-users-add', 'text': T('«إضافة مستخدم» يفتح نموذج حساب جديد.',
                                              '"Add user" opens a new account form.'),
             'more': T('النموذج بيطلب:\n'
                       '• «بحث في مستخدمي SOFTECH» واختار الموظف عشان يتربط بيه.\n'
                       '• كلمة المرور والاسم والهاتف وكود الموارد البشرية.\n'
                       '• الدور والفرع الأساسي وصلاحيات الوصول (كل الفروع، قنوات البيع، رؤية العملاء وأرقامهم).\n'
                       'الحساب مش بيتعمل غير بـ«إنشاء المستخدم». الزرار للمدير بس.',
                       'The form asks for:\n'
                       '• "Search SOFTECH users" and pick the employee to link.\n'
                       '• Password, name, phone and HR code.\n'
                       '• Role, main branch and access (all branches, sales channels, seeing customers and their phones).\n'
                       'Nothing is created until "Create user". The button is admin only.'),
             'label': T('إضافة مستخدم', 'Add user'),
             'when': T('لموظف جديد. للمدير فقط.', 'For a new employee. Admins only.')},
            {'target': 'admin-users-search', 'text': T('ابحث بالاسم أو اسم المستخدم.',
                                              'Search by name or username.'),
             'more': T('اكتب جزء من الاسم أو اسم الدخول والقائمة بتتفلتر وإنت بتكتب.\n'
                       'مفيد لما تدوّر على موظف معيّن عشان تعدّل دوره أو تعيد كلمة مروره.',
                       'Type part of the name or login and the list filters as you type.\n'
                       'Handy when looking for a specific employee to change their role or reset their password.'),
             'label': T('بحث بالاسم أو اسم المستخدم…', 'Search by name or username…'),
             'when': T('دوّر الأول قبل ما تضيف عشان ماتعملش حساب مكرر.', 'Search first before adding so you do not create a duplicate account.')},
            {'target': 'admin-users-role-filter', 'text': T('فلتر الدور.',
                                              'Role filter.'),
             'more': T('بيعرض مستخدمي دور واحد بس، زي كل الصيادلة أو كل الكول سنتر.\n'
                       'مفيد قبل ما تغيّر صلاحيات دور، عشان تعرف مين هيتأثر.',
                       'Shows users of one role only, such as all pharmacists or all call center staff.\n'
                       'Useful before changing a role\'s permissions, to see who will be affected.'),
             'label': T('كل الأدوار', 'All roles')},
            {'target': 'admin-users-status-filter', 'text': T('فلتر الحالة (نشط / موقوف).',
                                              'Status filter (active / disabled).'),
             'more': T('«نشط» للي يقدر يدخل، و«موقوف» للحسابات المعطّلة.\n'
                       'استخدم «موقوف» لو عايز ترجّع حساب موظف رجع الشغل.',
                       '"Active" for those who can log in, "Disabled" for deactivated accounts.\n'
                       'Use "Disabled" to find an account to reactivate for a returning employee.'),
             'label': T('كل الحالات', 'All statuses'),
             'when': T('راجع الموقوفين دورياً.', 'Review the disabled ones regularly.')},
            {'target': 'admin-users-table', 'text': T('المستخدمين: الدور والفرع وربط SOFTECH والحالة.',
                                              'The users: role, branch, SOFTECH link and status.'),
             'more': T('لكل مستخدم: اسمه واسم الدخول، الدور، الفرع («• شامل» لو له وصول لكل الفروع)، اسم مستخدم SOFTECH المربوط، ونشط أو موقوف.\n'
                       'لو خانة SOFTECH فاضية، المستخدم مش مربوط.',
                       'For each user: name and login, role, branch ("• all" if they can access every branch), the linked SOFTECH username, and active or disabled.\n'
                       'An empty SOFTECH cell means the user is not linked.'),
             'label': T('جدول المستخدمين', 'Users table'),
             'when': T('عمود SOFTECH فاضي «—» يعني الحساب مش مربوط.', 'An empty "—" SOFTECH column means the account is not linked.')},
            {'target': 'admin-users-actions', 'text': T('الإجراءات: تعديل، كلمة المرور، تعطيل/تفعيل، سجل النشاط.',
                                              'Actions: edit, password, deactivate/activate, activity log.'),
             'more': T('• ✎ «تعديل»: الدور والفرع وصلاحيات الوصول.\n'
                       '• 🔑 «إعادة تعيين كلمة المرور».\n'
                       '• 🚫 «تعطيل الحساب» بيتنفذ فوراً من غير تأكيد ويوقف الدخول من غير ما يمسح حاجة.\n'
                       '• 📋 «سجل النشاط»: الدخول وكل تغيير في الدور أو الفرع أو الصلاحيات. للمدير بس.',
                       '• ✎ "Edit": role, branch and access.\n'
                       '• 🔑 "Reset password".\n'
                       '• 🚫 "Deactivate account" applies at once without confirmation and stops login without deleting anything.\n'
                       '• 📋 "Activity log": logins and every role, branch or permission change. Admin only.'),
             'label': T('إجراءات', 'Actions'),
             'open_hint': T('يظهر للمدير بس.', 'Shown to admins only.')},
            {'target': 'admin-users-edit', 'label': T('✎ تعديل', '✎ Edit'),
             'text': T('يفتح نفس النموذج لتغيير الاسم أو الدور أو الفرع أو الوصول.', 'Opens the same form to change name, role, branch or access.'),
             'when': T('عند نقل موظف لفرع أو تغيير وظيفته. التغيير بيتسجل في سجل نشاطه.', 'When moving an employee to a branch or changing their job. Logged in their activity.'),
             'open_hint': _ROW},
            {'target': 'admin-users-reset-password', 'label': T('🔑 إعادة تعيين كلمة المرور', '🔑 Reset password'),
             'text': T('تكتب كلمة مرور جديدة وتأكيدها للمستخدم.', 'Type a new password and its confirmation for the user.'),
             'warn': T('سلّمها للموظف بنفسه بس، واطلب منه يغيّرها.', 'Hand it to the employee in person only, and ask them to change it.'),
             'open_hint': _ROW},
            {'target': 'admin-users-toggle-active', 'label': T('⊘ تعطيل الحساب / ✓ تفعيل', '⊘ Disable / ✓ Enable account'),
             'text': T('يوقف الدخول أو يرجّعه من غير ما يمسح المستخدم ولا تاريخه.', 'Stops or restores login without deleting the user or their history.'),
             'when': T('عطّل حساب أي موظف ساب الشغل في نفس اليوم.', 'Disable the account of anyone who leaves on the same day.'),
             'warn': T('بيتنفّذ فوراً من غير تأكيد — الموظف بيخرج من النظام.', 'Happens at once with no confirmation — the employee is locked out.'),
             'open_hint': _ROW},
            {'target': 'admin-users-activity-log', 'label': T('📋 سجل النشاط', '📋 Activity log'),
             'text': T('دخول وتغيير دور أو فرع أو صلاحيات لهذا المستخدم.', 'Logins and role, branch or permission changes for this user.'),
             'open_hint': _ROW},
            {'target': 'admin-users-softech-link', 'label': T('بحث في مستخدمي SOFTECH', 'Search SOFTECH users'),
             'text': T('اكتب اسمه واختاره من القائمة؛ يملا اسم المستخدم ويظهر «✓ تم اختيار».', 'Type and pick from the list; it fills the username and shows "✓ selected".'),
             'warn': T('من غير ربط مايقدرش يعتمد حاجة بتتنفّذ في SOFTECH باسمه.', 'Without the link they cannot approve anything executed in SOFTECH under their name.'),
             'open_hint': _NEW_DRAWER},
            {'target': 'admin-users-password', 'label': T('كلمة المرور *', 'Password *'),
             'text': T('10 حروف على الأقل، ومرفوضة لو شائعة أو أرقام بس أو شبه اسم المستخدم.', 'At least 10 characters; refused if common, digits only or close to the username.'),
             'open_hint': _NEW_DRAWER},
            {'target': 'admin-users-role', 'label': T('الدور *', 'Role *'),
             'text': T('الدور بيحدد هيشوف ويعمل إيه حسب مصفوفة الصلاحيات.', 'The role decides what they see and do, per the permissions matrix.'),
             'open_hint': _DRAWER},
            {'target': 'admin-users-branch', 'label': T('الفرع الأساسي', 'Main branch'),
             'text': T('فرع الموظف؛ «— المركز الرئيسي —» لموظفي الإدارة.', 'The employee\'s branch; "— Head office —" for HQ staff.'),
             'open_hint': _DRAWER},
            {'target': 'admin-users-access', 'label': T('صلاحيات الوصول', 'Access'),
             'text': T('كل الفروع، قنوات البيع المسموحة (فارغ = كلها)، عملاء كل الفروع، رقم هاتف العميل، و«الحساب نشط» في التعديل.',
                       'All branches, allowed sales channels (empty = all), all-branch customers, customer phone, and "Account active" when editing.'),
             'warn': T('رقم هاتف العميل بيانات شخصية — افتحه لمن يحتاجه بس.', 'Customer phone numbers are personal data — enable them only for those who need them.'),
             'open_hint': _DRAWER},
            {'target': 'admin-users-save', 'label': T('إنشاء المستخدم / حفظ التعديلات', 'Create user / Save changes'),
             'text': T('يحفظ. لو فيه خطأ (اسم مكرر، كلمة مرور ضعيفة) بيظهر فوق النموذج.', 'Saves. Any error (duplicate name, weak password) shows at the top of the form.'),
             'open_hint': _DRAWER},
        ],
        'updated': '2026-10-30',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
    {
        'key': 'admin.permissions',
        'routes': ['/permissions'],
        'title': T('مصفوفة الصلاحيات', 'Permissions matrix'),
        'summary': T('لكل دور × موديول × إجراء (عرض، إنشاء، تعديل، حذف، اعتماد، تصدير، إسناد، إنهاء): مسموح أو ممنوع. السيرفر يطبق نفس المصفوفة على كل طلب، والقائمة والأزرار تُخفى حسبها. المدير له وصول كامل غير قابل للتعديل.',
                     'For each role × module × action (view, create, edit, delete, approve, export, assign, finalize): allowed or denied. The server applies the same matrix to every request, and menus and buttons hide accordingly. Admins have full, non-editable access.'),
        'audience': T('المدير فقط.', 'Admins only.'),
        'tabs': [
            {'key': 'modules', 'title': T('صلاحيات الوحدات', 'Module permissions'), 'body': T('اختر الدور ← فعّل/أوقف كل إجراء لكل موديول، أو «منح/سحب الكل» ← «حفظ التغييرات». موديول «دليل الاستخدام» بإجراء «تعديل» = من يستطيع تعديل الشرح (المدربون).', 'Pick the role → toggle each action per module, or "grant/revoke all" → "Save changes". The "Help guide" module with the "edit" action = who may edit the help (trainers).')},
            {'key': 'notifiers', 'title': T('ظهور الإشعارات', 'Notification visibility'), 'body': T('لكل دور ولكل نوع إشعار: إظهار (يُنشأ ويظهر)، كتم (يُنشأ لكن لا يظهر)، إيقاف (لا يُنشأ). الافتراضي يتبع صلاحية «عرض» للموديول.', 'Per role and notification type: show (created and shown), mute (created, not shown), off (not created). The default follows the module\'s "view" permission.')},
        ],
        'related': ['admin.users', 'admin.erp_permissions'],
        'tour': [
            {'target': 'admin-permissions-view-tabs', 'text': T('صلاحيات الوحدات، أو ظهور الإشعارات لكل دور.',
                                              'Module permissions, or notification visibility per role.'),
             'more': T('• «صلاحيات الوحدات»: إيه اللي الدور يقدر يشوفه ويعمله في كل موديول.\n'
                       '• «🔔 ظهور الإشعارات»: لكل نوع إشعار — إظهار، كتم (بيتعمل بس مش بيظهر)، أو إيقاف (مش بيتعمل خالص).',
                       '• "Module permissions": what the role can see and do in each module.\n'
                       '• "🔔 Notification visibility": per notification type — show, mute (created but hidden), or off (not created at all).'),
             'label': T('صلاحيات الوحدات · 🔔 ظهور الإشعارات', 'Module permissions · 🔔 Notifications')},
            {'target': 'admin-permissions-roles', 'text': T('اختار الدور.',
                                              'Choose the role.'),
             'more': T('الجدول جنبه بيتغيّر حسب الدور المختار.\n'
                       'النقطة الصفرا جنب الدور معناها تغييرات لسه ما اتحفظتش. المدير مش في القائمة لأن له وصول كامل مش بيتعدّل.',
                       'The table beside it changes with the chosen role.\n'
                       'A yellow dot next to a role means unsaved changes. Admin is not listed because it has full, non-editable access.'),
             'label': T('الأدوار', 'Roles'),
             'when': T('المدير مش في القائمة: له وصول كامل ثابت.', 'Admin is not listed: it has fixed full access.')},
            {'target': 'admin-permissions-matrix', 'text': T('علّم الإجراءات المسموحة لكل وحدة — السيرفر بيطبّقها على كل طلب.',
                                              'Tick the allowed actions per module — the server enforces them on every request.'),
             'more': T('كل سطر وحدة وكل عمود إجراء (عرض، إنشاء، تعديل، حذف، اعتماد…). اضغط الخانة تفتحها أو تقفلها.\n'
                       '• «منح الكل / سحب الكل» في آخر السطر للوحدة كلها.\n'
                       '• تحت: «منح / سحب جميع الصلاحيات» للدور كله — بحذر.\n'
                       'وحدة «دليل الاستخدام» بإجراء «تعديل» = مين يقدر يعدّل الشرح.',
                       'Each row is a module, each column an action (view, create, edit, delete, approve…). Click a cell to turn it on or off.\n'
                       '• "Grant all / Revoke all" at the row end covers the whole module.\n'
                       '• Below: "Grant / Revoke all permissions" for the whole role — use with care.\n'
                       'The "Help guide" module with "edit" = who may edit the help.'),
             'label': T('الوحدة × عرض · إنشاء · تعديل…', 'Module × view · create · edit…'),
             'when': T('من غير «عرض» الوحدة كلها بتختفي من القائمة.', 'Without "view" the whole module disappears from the menu.'),
             'open_hint': _ROLE},
            {'target': 'admin-permissions-row-all', 'label': T('منح الكل / سحب الكل', 'Grant all / Revoke all'),
             'text': T('يفتح أو يقفل كل إجراءات وحدة واحدة مرة واحدة.', 'Turns every action of one module on or off at once.'),
             'open_hint': _ROLE},
            {'target': 'admin-permissions-role-all', 'label': T('منح جميع الصلاحيات | سحب جميع الصلاحيات', 'Grant all permissions | Revoke all'),
             'text': T('يفتح أو يقفل كل الوحدات للدور كله.', 'Turns every module on or off for the whole role.'),
             'warn': T('«منح جميع الصلاحيات» يدي الدور وصول قريب من المدير — راجعه قبل الحفظ.', '"Grant all" gives the role near-admin access — review before saving.'),
             'open_hint': _ROLE},
            {'target': 'admin-permissions-notifiers', 'label': T('إظهار · كتم · إيقاف', 'Show · mute · off'),
             'text': T('لكل إشعار: إظهار، كتم (يتسجل ومايظهرش)، أو إيقاف (مايتعملش خالص).', 'Per notification: show, mute (created, not shown) or off (not created at all).'),
             'warn': T('«إيقاف» مالوش أثر رجعي — الإشعارات اللي فاتت مش هترجع.', '"Off" is not retroactive — missed notifications will not come back.'),
             'open_hint': T('افتح «🔔 ظهور الإشعارات» واختار دور.', 'Open "🔔 Notification visibility" and pick a role.')},
            {'target': 'admin-permissions-legend', 'text': T('معنى الألوان: مسموح، ممنوع، تغيير غير محفوظ.',
                                              'The colours: allowed, denied, unsaved change.'),
             'more': T('✓ أخضر مسموح، × رمادي ممنوع، والنقطة الصفرا تحت الخانة تغيير لسه ما اتحفظش.\n'
                       'لو مش مدير هتلاقي «عرض فقط» — تشوف المصفوفة من غير ما تعدّل.',
                       'Green ✓ allowed, grey × denied, and a yellow dot under a cell is an unsaved change.\n'
                       'If you are not an admin you see "View only" — you can see the matrix but not edit it.'),
             'label': T('مسموح · ممنوع · تغيير غير محفوظ', 'Allowed · denied · unsaved change')},
            {'target': 'admin-permissions-save-bar', 'text': T('عدد التغييرات غير المحفوظة و«تراجع».',
                                              'The number of unsaved changes and "Undo".'),
             'more': T('بيعدّ كل خانة غيّرتها في كل الأدوار. «تراجع» بيرجّع كل التغييرات اللي ما اتحفظتش مرة واحدة.\n'
                       'الأزرار دي بتظهر بس لما يكون فيه تغيير.',
                       'It counts every cell you changed across all roles. "Undo" reverts all unsaved changes at once.\n'
                       'These buttons only appear when there is a change.'),
             'label': T('… تغيير غير محفوظ', '… unsaved changes')},
            {'target': 'admin-permissions-undo', 'label': T('تراجع', 'Undo'),
             'text': T('يرجّع كل التغييرات غير المحفوظة.', 'Reverts every unsaved change.'),
             'open_hint': T('يظهر لما يكون فيه تغيير غير محفوظ.', 'Shown when there is an unsaved change.')},
            {'target': 'admin-permissions-save', 'text': T('«حفظ التغييرات» — لا شيء يتطبّق قبل الحفظ.',
                                              '"Save changes" — nothing applies before saving.'),
             'more': T('بيحفظ كل التغييرات (وحدات وإشعارات) مرة واحدة، والرقم بين القوسين عددها. بعدها تظهر «✓ تم الحفظ».\n'
                       'الحفظ بيتسجّل باسمك في سجل نشاط المستخدمين. راجع قبل ما تحفظ — سحب «عرض» بيخفي الشاشة عن الدور كله.',
                       'It saves all changes (modules and notifications) at once; the number in brackets is how many. Then "✓ Saved" shows.\n'
                       'Saving is recorded under your name in the user activity log. Check first — removing "view" hides the screen from the whole role.'),
             'label': T('حفظ التغييرات (…)', 'Save changes (…)'),
             'warn': T('بيسري فوراً على كل مستخدمي الدور في كل الفروع.', 'Takes effect at once for every user of the role in every branch.'),
             'open_hint': T('يظهر لما يكون فيه تغيير غير محفوظ.', 'Shown when there is an unsaved change.'),
             'more': T('بيحفظ كل التغييرات (وحدات وإشعارات) مرة واحدة، والرقم بين القوسين عددها. بعدها تظهر «✓ تم الحفظ».\n'
                       'الحفظ بيتسجّل باسمك في سجل نشاط المستخدمين. راجع قبل ما تحفظ — سحب «عرض» بيخفي الشاشة عن الدور كله.',
                       'It saves all changes (modules and notifications) at once; the number in brackets is how many. Then "✓ Saved" shows.\n'
                       'Saving is recorded under your name in the user activity log. Check first — removing "view" hides the screen from the whole role.'),
         },
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-30',
    },
    {
        'key': 'admin.erp_permissions',
        'routes': ['/erp-permissions'],
        'title': T('صلاحيات SOFTECH الموروثة', 'Inherited SOFTECH permissions'),
        'summary': T('تُشتق صلاحيات الموديولات تلقائياً من مجموعة المستخدم في SOFTECH (SOFTECH هو المصدر، يُعاد البناء يومياً). هنا تراجع وتعدّل طريقة الاشتقاق.', 'Module permissions are derived automatically from the user\'s SOFTECH group (SOFTECH is the source, rebuilt daily). Here you review and adjust the derivation.'),
        'audience': T('المدير فقط.', 'Admins only.'),
        'tabs': [
            {'key': 'map', 'title': T('ربط الأنظمة بالوحدات', 'System → module map'), 'body': T('أي نظام في SOFTECH يعطي أي موديول هنا؛ أضف أو احذف ربطاً وأكّد الربط الغامض.', 'Which SOFTECH system grants which module here; add or remove a mapping and confirm ambiguous ones.')},
            {'key': 'groups', 'title': T('صلاحيات المجموعات', 'Group permissions'), 'body': T('لكل مجموعة SOFTECH: الموديولات المشتقة (عرض/تعديل/رؤية التكلفة والمال).', 'Per SOFTECH group: the derived modules (view/edit/see cost and money).')},
            {'key': 'systems', 'title': T('أنظمة Softech', 'SOFTECH systems'), 'body': T('مرجع أنظمة SOFTECH وعدد شاشاتها وهل هي مربوطة.', 'Reference of SOFTECH systems, their screen counts and whether they are mapped.')},
        ],
        'steps': [T('«إعادة الاشتقاق الآن» بعد أي تعديل لتطبيقه فوراً.', '"Re-derive now" after a change to apply it immediately.')],
        'tour': [
            {'target': 'admin-erp-permissions-header', 'text': T('صلاحيات الوحدات هنا مشتقة من مجموعة المستخدم في Softech، ويُعاد بناؤها يومياً.',
                                              'Module permissions here are derived from the user\'s Softech group and rebuilt daily.'),
             'more': T('كل مستخدم في SOFTECH تابع لمجموعة ليها صلاحيات على شاشات أنظمة SOFTECH. الصفحة دي بتترجم ده لصلاحيات على وحداتنا.\n'
                       'SOFTECH هو المصدر — مفيش هنا أي كتابة فيه، بس قراءة واشتقاق.',
                       'Every SOFTECH user belongs to a group with rights on SOFTECH system screens. This page translates that into rights on our modules.\n'
                       'SOFTECH is the source — nothing here writes to it; it only reads and derives.'),
             'label': T('صلاحيات Softech الموروثة', 'Inherited Softech permissions'),
             'when': T('لما تحتاج تعرف ليه موظف شايف وحدة أو مش شايفها.', 'When you need to know why an employee does or does not see a module.'),
         },
            {'target': 'admin-erp-permissions-rebuild', 'label': T('إعادة الاشتقاق الآن', 'Re-derive now'),
             'text': T('يعيد حساب صلاحيات كل مجموعة من الربط الحالي بدل ما تستنى البناء اليومي.', 'Recomputes every group\'s permissions from the current map instead of waiting for the daily rebuild.'),
             'when': T('بعد ما تراجع الربط. مش بيكتب حاجة في SOFTECH.', 'After reviewing the map. Nothing is written to SOFTECH.'),
             'more': T('بيعيد حساب صلاحيات كل المجموعات بالربط الحالي من غير ما تستنى البناء اليومي.\n'
                       'إضافة أو حذف ربط بيعيد الاشتقاق لوحده، فالزرار ده مفيد لو عايز تتأكد إن كل حاجة محدّثة.',
                       'It recalculates all groups\' permissions with the current mapping without waiting for the daily rebuild.\n'
                       'Adding or removing a mapping re-derives by itself, so this button is for making sure everything is up to date.'),
             'label': T('إعادة الاشتقاق الآن', 'Re-derive now'),
             'when': T('بعد ما تراجع الربط. مش بيكتب حاجة في SOFTECH.', 'After reviewing the map. Nothing is written to SOFTECH.')},
            {'target': 'admin-erp-permissions-tabs', 'text': T('التبويبات: ربط الأنظمة بالوحدات، صلاحيات المجموعات، وأنظمة Softech.',
                                              'Tabs: system → module map, group permissions, and Softech systems.'),
             'more': T('• «ربط الأنظمة بالوحدات»: أنهي نظام SOFTECH بيدّي أنهي وحدة.\n'
                       '• «صلاحيات المجموعات»: النتيجة لكل مجموعة.\n'
                       '• «أنظمة Softech»: مرجع بعدد شاشات كل نظام وهل هو مربوط ولا «— غير مربوط».',
                       '• "System → module map": which SOFTECH system grants which module.\n'
                       '• "Group permissions": the result for each group.\n'
                       '• "Softech systems": a reference with each system\'s screen count and whether it is mapped or "— not mapped".'),
             'label': T('الربط · المجموعات · الأنظمة', 'Map · groups · systems')},
            {'target': 'admin-erp-permissions-add-map', 'text': T('في «ربط الأنظمة بالوحدات»: نظام Softech والوحدة وملاحظة ثم «إضافة ربط».',
                                              'In "System → module map": Softech system, module and a note, then "Add mapping".'),
             'more': T('اكتب كود النظام (زي IM)، واختار الوحدة، وملاحظة توضّح السبب، واضغط «إضافة ربط».\n'
                       'الربط بيتحفظ والصلاحيات بتتشتق تاني فوراً — كل مستخدمي المجموعات اللي عندها النظام ده هياخدوا الوحدة.',
                       'Type the system code (like IM), choose the module, add a note explaining why, and press "Add mapping".\n'
                       'The mapping is saved and permissions are re-derived at once — users in groups with that system get the module.'),
             'label': T('نظام Softech · الوحدة · ملاحظة', 'SOFTECH system · module · note'),
             'open_hint': T('في تبويب «ربط الأنظمة بالوحدات».', 'On the "System → module map" tab.')},
            {'target': 'admin-erp-permissions-map-add', 'label': T('إضافة ربط', 'Add mapping'),
             'text': T('يضيف الربط ويعيد الاشتقاق على طول.', 'Adds the mapping and re-derives at once.'),
             'warn': T('ربط غلط يدي مجموعة كاملة وصول لوحدة مش بتاعتها.', 'A wrong mapping gives a whole group access to a module that is not theirs.'),
             'open_hint': T('في تبويب «ربط الأنظمة بالوحدات».', 'On the "System → module map" tab.')},
            {'target': 'admin-erp-permissions-map-card', 'label': T('كارت الوحدة', 'Module card'),
             'text': T('لكل وحدة: أنظمة SOFTECH اللي بتديها.', 'For each module: the SOFTECH systems that grant it.'),
             'when': T('أكّد الربط الغامض المكتوب في التنبيه الأصفر.', 'Confirm the ambiguous mapping noted in the yellow banner.'),
             'open_hint': T('في تبويب «ربط الأنظمة بالوحدات».', 'On the "System → module map" tab.')},
            {'target': 'admin-erp-permissions-map-delete', 'label': T('✕', '✕'),
             'text': T('يشيل ربط نظام من الوحدة ويعيد الاشتقاق.', 'Removes a system from the module and re-derives.'),
             'warn': T('بيتنفّذ فوراً من غير تأكيد — المجموعات ممكن تفقد الوحدة.', 'Happens at once with no confirmation — groups may lose the module.'),
             'open_hint': T('جنب كل رمز نظام في كروت الوحدات.', 'Next to every system code in the module cards.')},
            {'target': 'admin-erp-permissions-map', 'text': T('كل وحدة والأنظمة المربوطة بها، و✕ لإزالة ربط.',
                                              'Each module and the systems mapped to it; ✕ removes a mapping.'),
             'more': T('كارت لكل وحدة فيه أكواد أنظمة SOFTECH المربوطة بيها.\n'
                       '✕ بيشيل الربط فوراً من غير تأكيد ويعيد الاشتقاق — ممكن مستخدمين يفقدوا الوحدة، فاتأكد قبل ما تضغط.',
                       'A card per module with the SOFTECH system codes mapped to it.\n'
                       '✕ removes the mapping at once without confirmation and re-derives — users may lose the module, so be sure before pressing.'),
             'label': T('ربط الأنظمة بالوحدات', 'System-to-module map'),
             'when': T('لمراجعة أو تصحيح الأنظمة المربوطة بكل وحدة.', 'To check or fix the systems linked to each module.'),
         },
            {'target': 'admin-erp-permissions-groups', 'text': T('في «صلاحيات المجموعات»: لكل مجموعة ✓ عرض، ✎ تعديل، $ رؤية التكلفة.',
                                              'In "Group permissions": per group ✓ view, ✎ edit, $ see cost.'),
             'more': T('سطر لكل مجموعة SOFTECH وعمود لكل وحدة: ✓ عرض، ✎ تعديل، $ رؤية التكلفة والمال، و· لا شيء.\n'
                       'راجعه بعد أي تغيير في الربط عشان تتأكد إن مفيش مجموعة أخدت أكتر من اللازم.',
                       'A row per SOFTECH group and a column per module: ✓ view, ✎ edit, $ see cost and money, · nothing.\n'
                       'Review it after any mapping change to make sure no group got more than it should.'),
             'label': T('صلاحيات المجموعات', 'Group permissions'),
             'when': T('راجع «$» كويس — دي بتكشف التكلفة.', 'Check "$" carefully — it reveals costs.'),
             'open_hint': T('افتح تبويب «صلاحيات المجموعات».', 'Open the "Group permissions" tab.'),
             'more': T('سطر لكل مجموعة SOFTECH وعمود لكل وحدة: ✓ عرض، ✎ تعديل، $ رؤية التكلفة والمال، و· لا شيء.\n'
                       'راجعه بعد أي تغيير في الربط عشان تتأكد إن مفيش مجموعة أخدت أكتر من اللازم.',
                       'A row per SOFTECH group and a column per module: ✓ view, ✎ edit, $ see cost and money, · nothing.\n'
                       'Review it after any mapping change to make sure no group got more than it should.'),
         },
            {'target': 'admin-erp-permissions-systems', 'label': T('أنظمة Softech', 'SOFTECH systems'),
             'text': T('كل نظام: عدد شاشاته، مثال، ومربوط بأي وحدة أو «— غير مربوط».', 'Each system: screen count, a sample, and which module it maps to or "— unmapped".'),
             'open_hint': T('افتح تبويب «أنظمة Softech».', 'Open the "SOFTECH systems" tab.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-30',
    },
    {
        'key': 'admin.settings',
        'routes': ['/settings'],
        'title': T('إعدادات النظام', 'System settings'),
        'summary': T('كل إعدادات النظام في تبويبات.', 'All system settings in tabs.'),
        'audience': T('المدير (والصيدلي لإعدادات فرعه).', 'Admins (pharmacists for their branch settings).'),
        'tabs': [
            {'key': 'general', 'title': T('⚙️ عام', '⚙️ General'), 'body': T('بيانات الصيدلية (الاسم، الشعار، الموقع، واتساب الرئيسي، أرقام الاتصال — تظهر في الإيصالات ورسائل واتساب) ولغة الواجهة.', 'Pharmacy details (name, tagline, website, main WhatsApp, contact numbers — shown on receipts and WhatsApp messages) and the interface language.')},
            {'key': 'appearance', 'title': T('🎨 المظهر', '🎨 Appearance'), 'body': T('ألوان الهوية: الأساسي (الأزرار والقائمة)، الثانوي، ولون التنبيه.', 'Brand colours: primary (buttons and menu), secondary, and the alert colour.')},
            {'key': 'branches', 'title': T('🏪 الفروع', '🏪 Branches'), 'body': T('لكل فرع: يعمل / موقوف مؤقتاً / مغلق، الميزات المتاحة (الحجوزات، التحويلات، الجرد، النواقص…)، البيانات، وإحداثيات الموقع (لازمة لتحقق الحضور والاستلام الجغرافي — «استخدم موقعي الحالي» من داخل الفرع)، ومواعيد العمل (أو 24 ساعة) التي يستخدمها تدقيق المخزون لكشف الإدخال خارج المواعيد — فترة بأكواد مستندات تنطبق عليها فقط.', 'Per branch: working / paused / closed, enabled features (reservations, transfers, count, shortages…), details, location coordinates (needed for attendance and pickup geo-checks — "use my current location" from inside the branch), and working hours (or 24 hours) used by the stock audit to spot entries outside hours — a window with document codes applies to those documents only.')},
            {'key': 'reservations', 'title': T('📋 الحجوزات', '📋 Reservations'), 'body': T('معاملات الحجوزات (المدد، التنبيهات، الحالات العالقة…).', 'Reservation parameters (durations, alerts, stuck thresholds…).')},
            {'key': 'transfers', 'title': T('🔀 التحويل', '🔀 Transfers'), 'body': T('قواعد التحويلات.', 'Transfer rules.')},
            {'key': 'notifications', 'title': T('🔔 الإشعارات', '🔔 Notifications'), 'body': T('مفاتيح تشغيل أنواع الإشعارات.', 'On/off gates for notification types.')},
            {'key': 'sync', 'title': T('⟳ المزامنة', '⟳ Sync'), 'body': T('جدول المزامنة مع SOFTECH وحجم الدفعات.', 'The SOFTECH sync schedule and batch sizes.')},
            {'key': 'vouchers', 'title': T('🎫 القسائم', '🎫 Vouchers'), 'body': T('إعدادات رموز التحقق وحدود القيم.', 'OTP settings and value limits.')},
            {'key': 'dropdowns', 'title': T('📝 القوائم المنسدلة', '📝 Dropdowns'), 'body': T('خيارات القوائم المنسدلة في الشاشات (قنوات الحجز، أولويات الحجز، حالات التحويل…): أضف خياراً (تسمية عربية، قيمة، أيقونة) أو عطّله.', 'The dropdown options used in screens (reservation channels, priorities, transfer statuses…): add an option (Arabic label, value, icon) or disable it.')},
        ],
        'tips': [T('تغيير لغة الواجهة فوري ويُحفظ في المتصفح.', 'Changing the interface language is instant and saved in the browser.')],
        'tour': [
            {'target': 'admin-settings-header', 'text': T('إعدادات النظام؛ غير المدير يرى «عرض فقط».',
                                              'System settings; non-admins see "View only".'),
             'more': T('هنا بتتظبط بيانات الصيدلية والفروع وقواعد كل موديول.\n'
                       'المدير بس اللي يعدّل؛ الصيدلي بيشوف الإعدادات مع شارة «عرض فقط — يحتاج صلاحية مدير للتعديل».',
                       'Pharmacy details, branches and each module\'s rules are set here.\n'
                       'Only admins edit; pharmacists see the settings with a "View only — admin required to edit" badge.')},
            {'target': 'admin-settings-tabs', 'text': T('أقسام الإعدادات: عام، المظهر، الفروع، الحجوزات، التحويل، الإشعارات، المزامنة، القسائم، القوائم المنسدلة.',
                                              'Settings sections: General, Appearance, Branches, Reservations, Transfers, Notifications, Sync, Vouchers, Dropdowns.'),
             'more': T('اضغط القسم من العمود الجانبي والمحتوى بيتغيّر جنبه.\n'
                       '• «الحجوزات» و«التحويل» و«الإشعارات» و«المزامنة» و«القسائم»: قواعد كل موديول.\n'
                       '• «المظهر»: ألوان الهوية.',
                       'Click a section in the side column and the content beside it changes.\n'
                       '• "Reservations", "Transfers", "Notifications", "Sync" and "Vouchers": each module\'s rules.\n'
                       '• "Appearance": brand colours.')},
            {'target': 'admin-settings-content', 'text': T('إعدادات القسم المختار تظهر هنا؛ التعديل للمدير فقط.',
                                              'The selected section\'s settings appear here; editing is admin only.'),
             'more': T('كل إعداد في سطر بقيمته الحالية. اضغط «تعديل» جنبه، غيّر القيمة، وبعدين «حفظ» — كل إعداد بيتحفظ لوحده وتظهر «تم الحفظ ✓».\n'
                       'التغيير بيأثر على شغل الموديول على طول، فغيّر بس اللي فاهم تأثيره.',
                       'Each setting is a row with its current value. Click "Edit" next to it, change the value, then "Save" — each setting saves on its own and "Saved ✓" shows.\n'
                       'The change affects how the module works right away, so only change what you understand.')},
            {'target': 'admin-settings-general', 'text': T('في «عام»: لغة الواجهة وبيانات الصيدلية الظاهرة في الإيصالات وواتساب.',
                                              'In "General": interface language and pharmacy details shown on receipts and WhatsApp.'),
             'more': T('• لغة الواجهة (العربية / English): التغيير فوري ومتسجّل في المتصفح.\n'
                       '• «معلومات سلسلة الصيدليات»: بتظهر في إيصالات العملاء ورسائل واتساب ورمز QR — راجعها كويس.',
                       '• Interface language (Arabic / English): the change is instant and saved in the browser.\n'
                       '• "Pharmacy chain profile": shown on customer receipts, WhatsApp messages and the QR code — check it carefully.')},
            {'target': 'admin-settings-branches', 'text': T('في «الفروع»: بطاقة لكل فرع بحالته وميزاته وبياناته وموقعه.',
                                              'In "Branches": a card per branch with status, features, details and location.'),
             'more': T('• «✎ تعديل»: الاسم والهاتف والعنوان والإحداثيات («استخدم موقعي الحالي» وإنت جوه الفرع).\n'
                       '• «نشط» و«قيد التشغيل» بيتغيّروا بضغطة واحدة فوراً.\n'
                       '• «الميزات المتاحة»: اضغط على الميزة تفعّلها أو توقفها للفرع.\n'
                       'من غير إحداثيات، تحقق الحضور والاستلام الجغرافي مش هيشتغل.',
                       '• "✎ Edit": name, phone, address and coordinates ("use my current location" while inside the branch).\n'
                       '• "Active" and "Operational" switch with one click, immediately.\n'
                       '• "Available features": click a feature to enable or disable it for the branch.\n'
                       'Without coordinates, attendance and pickup geo-checks will not work.')},
            {'target': 'admin-settings-dropdowns', 'text': T('في «القوائم المنسدلة»: خيارات القوائم المستخدمة في الشاشات مثل قنوات الحجز.',
                                              'In "Dropdowns": the options used in screens, such as reservation channels.'),
             'more': T('• «+ إضافة خيار جديد»: التسمية العربية والقيمة إجباريين، والإنجليزي والأيقونة اختياريين.\n'
                       '• «مفعّل / معطّل» بيخفي الخيار من الشاشات من غير ما يمسحه.\n'
                       '• ✕ بيمسح بعد تأكيد، والخيارات «ثابت» مش بتتمسح.',
                       '• "+ Add new option": Arabic label and value are required; English label and icon are optional.\n'
                       '• "Enabled / Disabled" hides the option from screens without deleting it.\n'
                       '• ✕ deletes after a confirmation; "System" options cannot be deleted.')},
        ],
        'tips': [
            T('تغيير لغة الواجهة فوري ويُحفظ في المتصفح.', 'Changing the interface language is instant and saved in the browser.'),
            T('كل تعديل بيتحقق من صلاحيتك على السيرفر (مصفوفة الصلاحيات، موديول الإعدادات): القراءة متاحة للكل، لكن تعديل الإعدادات والقوائم وبيانات الصيدلية يحتاج «تعديل» (أو «إضافة» / «حذف» للقوائم).',
              'Every change is checked on the server (Permissions Matrix, settings module): anyone can read, but changing settings, dropdown lists and the pharmacy profile needs "edit" (or "create" / "delete" for list options).'),
        ],
        'tour': [
            {'target': 'admin-settings-tabs', 'label': T('عام · المظهر · الفروع · …', 'General · Appearance · Branches · …'),
             'text': T('كل مجموعة إعدادات في تبويب: عام، المظهر، الفروع، الحجوزات، التحويل، الإشعارات، المزامنة، القسائم، القوائم.',
                       'Each settings group has a tab: general, appearance, branches, reservations, transfers, notifications, sync, vouchers, dropdowns.')},
            {'target': 'admin-settings-language', 'label': T('العربية · English', 'العربية · English'),
             'text': T('لغة الواجهة واتجاهها. التغيير فوري ومن غير إعادة تحميل.', 'Interface language and direction. The change is instant, no reload.'),
             'open_hint': T('في تبويب «عام».', 'On the "General" tab.')},
            {'target': 'admin-settings-profile-edit', 'label': T('✎ تعديل', '✎ Edit'),
             'text': T('يعدّل بيانات السلسلة: الاسم، الشعار، الموقع، واتساب، أرقام الاتصال، التذييل. بتظهر في الإيصال ورسائل واتساب ورمز QR.',
                       'Edits the chain profile: name, tagline, website, WhatsApp, contact numbers, footer. Shown on receipts, WhatsApp and the QR code.'),
             'warn': T('رقم واتساب غلط = رمز QR في كل إيصال يودّي لرقم غلط.', 'A wrong WhatsApp number = the QR on every receipt goes to the wrong number.'),
             'open_hint': T('في تبويب «عام» تحت «معلومات سلسلة الصيدليات».', 'On the "General" tab under "Pharmacy chain profile".')},
            {'target': 'admin-settings-setting-edit', 'label': T('تعديل', 'Edit'),
             'text': T('يفتح الإعداد للتعديل، وبعدها «حفظ» أو «إلغاء». كل إعداد عليه مفتاحه (key) ووصفه.',
                       'Opens the setting for editing, then "Save" or "Cancel". Each setting shows its key and description.'),
             'warn': T('بعض الإعدادات مفاتيح تشغيل — «نعم/لا» بيغيّر سلوك النظام لكل الفروع فوراً.',
                       'Some settings are on/off switches — "Yes/No" changes system behaviour for every branch at once.'),
             'open_hint': T('في أي تبويب إعدادات (الحجوزات، الإشعارات، المزامنة…)، للمدير.', 'On any settings tab (reservations, notifications, sync…), for admins.')},
            {'target': 'admin-settings-branch-edit', 'label': T('✎ تعديل', '✎ Edit'),
             'text': T('يعدّل اسم الفرع وهاتفه وعنوانه وإحداثياته، و«استخدم موقعي الحالي» من جوه الفرع.',
                       'Edits the branch name, phone, address and coordinates, with "use my current location" from inside the branch.'),
             'when': T('من غير إحداثيات الحضور والاستلام الجغرافي مش هيشتغلوا.', 'Without coordinates, attendance and pickup geo-checks do not work.'),
             'open_hint': _BRANCHES},
            {'target': 'admin-settings-branch-state', 'label': T('نشط · قيد التشغيل', 'Active · Operational'),
             'text': T('«نشط» مقفول = الفرع مغلق. «قيد التشغيل» مقفول = موقوف مؤقتاً (صيانة، جرد).',
                       '"Active" off = branch closed. "Operational" off = temporarily paused (maintenance, stock count).'),
             'warn': T('بيتحفظ بضغطة واحدة من غير تأكيد. الفرع المغلق مابيقبلش معاملات جديدة.', 'Saved in one click with no confirmation. A closed branch takes no new transactions.'),
             'open_hint': _BRANCHES},
            {'target': 'settings-branch-hours', 'label': T('🕘 مواعيد العمل', '🕘 Working hours'),
             'text': T('فترات العمل أو «يعمل 24 ساعة». تدقيق المخزون بيكشف أي إدخال برّه المواعيد.', 'Working windows or "open 24 hours". The stock audit flags any entry outside these hours.'),
             'when': T('فترة عليها أكواد مستندات بتنطبق على المستندات دي بس.', 'A window with document codes applies to those documents only.'),
             'open_hint': _BRANCHES},
            {'target': 'admin-settings-branch-features', 'label': T('الميزات المتاحة', 'Enabled features'),
             'text': T('اضغط ميزة تشغّلها أو توقفها للفرع: الحجوزات، التحويلات، القسائم، الجرد، النواقص، الإشعارات.',
                       'Click a feature to turn it on or off for the branch: reservations, transfers, vouchers, count, shortages, notifications.'),
             'warn': T('الإيقاف فوري — الفرع مش هيقدر يستخدم الميزة.', 'Turning off is instant — the branch can no longer use the feature.'),
             'open_hint': _BRANCHES},
            {'target': 'admin-settings-dropdown-add', 'label': T('+ إضافة خيار جديد', '+ Add new option'),
             'text': T('يضيف خيار لقائمة: التسمية العربية والقيمة (key) مطلوبين، والإنجليزي والأيقونة اختياري.',
                       'Adds an option to a list: Arabic label and value (key) required; English label and icon optional.'),
             'when': T('عشان توقف خيار من غير ما تمسحه اضغط «مفعّل» يبقى «معطّل».', 'To retire an option without deleting it, click "Enabled" to make it "Disabled".'),
             'open_hint': T('افتح تبويب «📝 القوائم المنسدلة».', 'Open the "📝 Dropdowns" tab.')},
            {'target': 'admin-settings-theme-save', 'label': T('💾 حفظ المظهر', '💾 Save theme'),
             'text': T('يحفظ ألوان الهوية والخط للنظام كله. «↺ استعادة الافتراضي» يرجّع ألوان الهوية.',
                       'Saves the brand colours and font for the whole system. "↺ Reset to brand default" restores them.'),
             'open_hint': T('افتح تبويب «🎨 المظهر» وغيّر حاجة.', 'Open the "🎨 Appearance" tab and change something.')},
        ],
        'updated': '2026-10-30',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
    {
        'key': 'admin.sync',
        'routes': ['/sync'],
        'title': T('المزامنة مع SOFTECH', 'SOFTECH sync'),
        'summary': T('حالة اتصال الشبكة (المركز الرئيسي + كل الفروع: متصل، غير متصل، منقطع باستمرار) وحالة المزامنة: آخر مزامنة ومدتها، هل المجدول يعمل، وسجل كل عملية. تتحدث تلقائياً كل 5 دقائق.',
                     'Network connection status (HQ + every branch: connected, disconnected, persistently down) and sync status: last sync and duration, whether the scheduler runs, and a log of every run. Refreshes every 5 minutes.'),
        'audience': T('المدير فقط.', 'Admins only.'),
        'steps': [
            T('«فحص الآن» لاختبار اتصال نقطة. «مزامنة الآن» لمزامنة فورية، و«مزامنة كاملة (90 يوم)» لإعادة بناء أوسع.', '"Check now" tests a node\'s connection. "Sync now" runs an immediate sync, "Full sync (90 days)" a wider rebuild.'),
            T('لو ظهر «المجدول متوقف — المهام لا تعمل» فالمهام التلقائية (المتابعات، التنبيهات، المزامنة الدورية) متوقفة — أعد تشغيل خدمة السيرفر.', 'If "scheduler stopped — jobs not running" appears, automatic jobs (follow-ups, alerts, periodic sync) are stopped — restart the server service.'),
            T('لو ظهر «المجدول متوقف — المهام لا تعمل» فالمهام التلقائية (المتابعات، التنبيهات، المزامنة الدورية) متوقفة — أعد تشغيل خدمة الخادم.', 'If "scheduler stopped — jobs not running" appears, automatic jobs (follow-ups, alerts, periodic sync) are stopped — restart the server service.'),
        ],
        'tips': [T('النقطة «منقطعة باستمرار» بعد عدة محاولات فاشلة متتالية — تحقق من اتصال الفرع.', 'A node is "persistently down" after several consecutive failures — check the branch connection.'),
                 T('المزامنة قراءة فقط من SOFTECH إلى النظام؛ لا تكتب أي شيء في SOFTECH.', 'Sync only reads from SOFTECH into the system; it writes nothing to SOFTECH.'),
                 T('«حمل SOFTECH» يعرض كم مرة اتصلنا بالسيرفر وكم استعلاماً وصفاً سحبنا وكم استغرق — حسب المهمة أو الكود أو السيرفر. الأثقل في أول الجدول؛ الأرقام تُحفظ كل دقيقة تقريباً.',
                   '"SOFTECH load" shows how many times we logged in to the server, how many queries and rows we pulled and how long it took — by job, code or server. The heaviest come first; figures are saved about once a minute.')],
        'tour': [
            {'target': 'admin-sync-status', 'text': T('حالة المزامنة مع SOFTECH — لو فشلت، السبب مكتوب هنا.',
                                              'The SOFTECH sync status — if it failed, the reason is shown here.'),
             'more': T('النقطة الملونة: أخضر «المزامنة تعمل بشكل طبيعي»، أصفر «جارٍ المزامنة الآن»، أحمر «فشلت آخر مزامنة» ومعاها رسالة الخطأ.\n'
                       'كمان هتلاقي وقت آخر مزامنة وعدد السجلات والمدة. الحالة بتتحدّث لوحدها.',
                       'The coloured dot: green "Sync running normally", amber "Syncing now", red "Last sync failed" with the error message.\n'
                       'You also see the last sync time, record count and duration. The status refreshes by itself.'),
             'label': T('حالة المزامنة', 'Sync status'),
             'when': T('أول حاجة تبص عليها لو حد قال «البيانات قديمة».', 'The first thing to check when someone says "the data is old".')},
            {'target': 'admin-sync-scheduler', 'label': T('المجدول متوقف — المهام لا تعمل', 'Scheduler stopped — jobs not running'),
             'text': T('المهام التلقائية (المزامنة الدورية، المتابعات، التنبيهات) واقفة، مع آخر نبضة.', 'Automatic jobs (periodic sync, follow-ups, alerts) are stopped, with the last heartbeat.'),
             'when': T('بلّغ مسؤول السيرفر يشغّل المجدول فوراً.', 'Ask the server admin to start the scheduler at once.'),
             'open_hint': T('بيظهر بس لما المجدول يقف — غيابه علامة كويسة.', 'Shown only when the scheduler stops — its absence is good.')},
            {'target': 'admin-sync-now', 'text': T('«مزامنة الآن» تجيب آخر التغييرات من SOFTECH.',
                                              '"Sync now" pulls the latest changes from SOFTECH.'),
             'more': T('بتسحب الفروع والأصناف والمخزون والعملاء والمبيعات والمستخدمين من SOFTECH — قراءة بس، مفيش كتابة فيه.\n'
                       'بتشتغل في الخلفية والنتيجة تظهر في الحالة والسجل. الزرار بيتقفل طول ما فيه مزامنة شغالة، ومش بتتكرر فوق بعض.',
                       'It pulls branches, items, stock, customers, sales and users from SOFTECH — read only, nothing is written to it.\n'
                       'It runs in the background and the result shows in the status and log. The button is disabled while a sync runs, and runs never stack.'),
             'label': T('↻ مزامنة الآن', '↻ Sync now'),
             'when': T('بعد تغيير مهم في SOFTECH ومش عايز تستنى الدورة. لو فيه مزامنة شغالة مش هيبدأ تانية.',
                       'After an important SOFTECH change when you do not want to wait. It will not start a second run.')},
            {'target': 'admin-sync-full', 'text': T('«مزامنة كاملة» تقيلة (90 يوم) — استخدمها بس لو فيه بيانات ناقصة.',
                                              '"Full sync" is heavy (90 days) — use it only when data is missing.'),
             'more': T('زي «مزامنة الآن» بس بتعيد سحب مبيعات آخر 90 يوم كاملة، فبتاخد وقت أطول بكتير.\n'
                       'استخدمها لو فيه مبيعات قديمة ناقصة أو بعد انقطاع طويل، ويُفضّل في وقت هادي.',
                       'Like "Sync now" but re-pulls the full last 90 days of sales, so it takes much longer.\n'
                       'Use it when older sales are missing or after a long outage, preferably at a quiet time.'),
             'label': T('مزامنة كاملة (90 يوم)', 'Full sync (90 days)'),
             'warn': T('تقيلة وبتاخد وقت وبتحمّل على SOFTECH — استخدمها بس لو فيه بيانات ناقصة، ويفضّل برّه وقت الذروة.',
                       'Heavy, slow and loads SOFTECH — use only when data is missing, ideally outside peak hours.')},
            {'target': 'admin-sync-branch-health', 'text': T('حالة اتصال المركز والفروع.',
                                              'The connection status of head office and branches.'),
             'more': T(
                 'لكل نقطة: «متصل» (بزمن الاستجابة)، «غير متصل»، أو «منقطع باستمرار» بعد محاولات فاشلة متتالية، مع آخر محاولة وآخر اتصال.\n«🔄 فحص الآن» يختبر الاتصال فوراً. لو فرع منقطع، بياناته مش هتتحدث لحد ما يرجع — كلّم الفرع.',
                 'For each node: "Connected" (with response time), "Disconnected", or "Persistently down" after consecutive failures, with last attempt and last connection.\n"🔄 Check now" tests immediately. If a branch is down its data will not update until it is back — contact the branch.'),
             'label': T('حالة اتصال الشبكة', 'Network connection status'),
             'when': T('فرع «منقطع باستمرار» = بياناته مش بتتحدث — كلّم الفرع يراجع الشبكة.', 'A "persistently down" branch = its data is not updating — ask the branch to check the network.')},
            {'target': 'admin-sync-probe', 'label': T('🔄 فحص الآن', '🔄 Check now'),
             'text': T('يختبر الاتصال بكل نقطة دلوقتي.', 'Tests every node\'s connection right now.'),
             'when': T('بعد ما الفرع يقول إنه صلّح الشبكة.', 'After the branch says it fixed the network.')},
            {'target': 'admin-sync-softech-load', 'text': T('«حمل SOFTECH»: ما نطلبه من السيرفر — اختر الفترة، ثم اعرض حسب المهمة أو الكود أو السيرفر.',
                                              '"SOFTECH load": what we ask of the server — pick a period, then group by job, code or server.'),
             'label': T('حمل SOFTECH', 'SOFTECH load'),
             'when': T('لما SOFTECH يبقى بطيء في الفروع — شوف أنهي مهمة بتسحب أكتر.', 'When SOFTECH is slow at the branches — see which job pulls the most.'),
             'warn': T('أرقام للقراءة بس — متوقفش مهمة تقيلة من غير ما ترجع لمسؤول السيرفر.', 'Read-only figures — do not stop a heavy job without checking with the server admin.')},
            {'target': 'admin-sync-logs', 'text': T('سجل المزامنة.',
                                              'The sync log.'),
             'more': T(
                 'كل عملية: نجح أو فشل، وقت البداية والنهاية، عدد السجلات والمدة، ورسالة الخطأ لو فشلت.\nوتحتها عدد السجلات لكل جدول — مفيد تعرف أنهي جزء (أصناف، عملاء، مبيعات) اتحدّث.',
                 'Each run: success or failure, start and end time, record count and duration, and the error if it failed.\nBelow it the record count per table — useful to see which part (items, customers, sales) was updated.'),
             'label': T('سجل المزامنة', 'Sync log'),
             'when': T('جدول عدده صفر وهو المفروض يتحدث = مشكلة في الجدول ده.', 'A table at zero that should update = a problem with that table.')},
        ],
        'updated': '2026-10-30',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
    },
    {
        'key': 'admin.audit',
        'routes': ['/audit'],
        'title': T('سجلات المراجعة والمراقبة', 'Audit & monitoring'),
        'summary': T('تتبع كل إجراء مهم وكشف الأنماط المشبوهة لحماية العمليات.', 'Track every important action and detect suspicious patterns to protect operations.'),
        'audience': T('المدير والمشرف ومدير الجودة.', 'Admins, supervisors and the quality manager.'),
        'tabs': [
            {'key': 'flags', 'title': T('الإشارات المشبوهة', 'Suspicious flags'), 'body': T('أنماط يكشفها النظام (إلغاءات متكررة، تعديلات متكررة، عدم تطابق ERP، نشاط خارج الدوام) بدرجة خطورتها. «مراجعة» ← القرار: راجعت، تجاهل، أو تصعيد مع ملاحظة. «فحص الآن» لتشغيل الكشف.', 'Patterns the system detects (repeated cancellations, repeated edits, ERP mismatch, out-of-hours activity) by severity. "Review" → decision: reviewed, ignore or escalate with a note. "Scan now" runs detection.')},
            {'key': 'logs', 'title': T('سجل الإجراءات', 'Action log'), 'body': T('من فعل ماذا ومتى ومن أي عنوان IP، مع التغييرات قبل وبعد — صفِّ بنوع الإجراء (إنشاء حجوزات، تغيير حالة، اعتماد تحويلات، دخول، محاولات فاشلة، مزامنة…).', 'Who did what, when and from which IP, with before/after changes — filter by action (reservations created, status changes, transfer approvals, logins, failed attempts, sync…).')},
        ],
        'tour': [
            {'target': 'admin-audit-tabs', 'text': T('«الإشارات المشبوهة» أو «سجل الإجراءات».',
                                              '"Suspicious flags" or "Action log".'),
             'more': T('• «⚠️ الإشارات المشبوهة»: أنماط النظام كشفها وتحتاج حد يراجعها.\n'
                       '• «📋 سجل الإجراءات»: كل حدث مهم بالمستخدم والكيان والوقت.\n'
                       'ابدأ بالإشارات المفتوحة، وارجع للسجل لما تحتاج تفاصيل.',
                       '• "⚠️ Suspicious flags": patterns the system detected that need someone to review.\n'
                       '• "📋 Action log": every important event with user, entity and time.\n'
                       'Start with open flags, and go to the log when you need details.'),
             'label': T('⚠️ الإشارات المشبوهة · 📋 سجل الإجراءات', '⚠️ Suspicious flags · 📋 Action log')},
            {'target': 'admin-audit-summary', 'label': T('ملخص الإشارات المفتوحة', 'Open flags summary'),
             'text': T('عدد الإشارات المفتوحة لكل نمط: إلغاءات متكررة، تعديلات متكررة، عدم تطابق ERP، نشاط خارج الدوام.',
                       'Open flags per pattern: repeated cancellations, repeated edits, ERP mismatch, out-of-hours activity.'),
             'open_hint': T('يظهر لو فيه إشارات مفتوحة.', 'Shown when there are open flags.')},
            {'target': 'admin-audit-flag-filters', 'text': T('فلترة الإشارات: مفتوح، مراجع، الكل، وحسب الخطورة.',
                                              'Filter flags: open, reviewed, all, and by severity.'),
             'more': T('• «مفتوح» (الافتراضي): اللي لسه محدش راجعه.\n'
                       '• «مراجع» أو «الكل» عشان تشوف القرارات اللي اتاخدت.\n'
                       '• الخطورة: حرج، تحذير، معلومة — ابدأ بـ«حرج».',
                       '• "Open" (default): not yet reviewed.\n'
                       '• "Reviewed" or "All" to see decisions already taken.\n'
                       '• Severity: critical, warning, info — start with "critical".'),
             'label': T('مفتوح · مراجع · الكل · الخطورة', 'Open · reviewed · all · severity'),
             'when': T('ابدأ بـ«مفتوح» + «حرج».', 'Start with "Open" + "Critical".'),
             'open_hint': _FLAGS},
            {'target': 'admin-audit-scan', 'text': T('«🔍 فحص الآن» يشغّل كشف الأنماط على آخر 24 ساعة.',
                                              '"🔍 Scan now" runs pattern detection over the last 24 hours.'),
             'more': T('الكشف بيدوّر في نشاط آخر 24 ساعة على إلغاءات وتعديلات متكررة، عدم تطابق مع ERP، ونشاط خارج الدوام.\n'
                       'في الآخر بتظهر رسالة بعدد الإشارات الجديدة، وبتنضاف للقائمة تحت «مفتوح».',
                       'Detection scans the last 24 hours for repeated cancellations and edits, ERP mismatches and after-hours activity.\n'
                       'At the end a message shows the number of new flags, which join the list under "Open".'),
             'label': T('🔍 فحص الآن', '🔍 Scan now'),
             'when': T('قبل المراجعة اليومية أو بعد حادثة.', 'Before the daily review or after an incident.'),
             'open_hint': _FLAGS},
            {'target': 'admin-audit-flags', 'text': T('الإشارات بنوعها وخطورتها والموظف والفرع وعدد الأحداث؛ تظهر عند وجود إشارات.',
                                              'Flags with type, severity, staff, branch and event count; shown when flags exist.'),
             'more': T('كل إشارة: النوع والوصف، الخطورة والحالة، الموظف وفرعه، عدد الأحداث وإمتى اتكشفت، وملاحظة المراجعة لو اتراجعت.\n'
                       'الإشارة مش اتهام — هي سبب إنك تبص وتتأكد.',
                       'Each flag: type and description, severity and status, the staff member and branch, event count and when detected, and the review note if reviewed.\n'
                       'A flag is not an accusation — it is a reason to look and verify.'),
             'label': T('قائمة الإشارات', 'Flags list'),
             'when': T('ابدأ بالإشارات المفتوحة الأخطر («حرج»).', 'Start with the open flags of the highest severity ("Critical").'),
         },
            {'target': 'admin-audit-review', 'text': T('«مراجعة» على الإشارة المفتوحة لتسجيل القرار مع ملاحظة.',
                                              '"Review" on an open flag records a decision with a note.'),
             'more': T('بيفتح نافذة فيها تفاصيل الإشارة وتختار: «✓ راجعت»، «— تجاهل»، أو «🚨 تصعيد»، مع ملاحظة اختيارية، وبعدين «تأكيد القرار».\n'
                       'الإشارة بتطلع من «مفتوح» والملاحظة بتفضل ظاهرة عليها للي بعدك.',
                       'It opens a window with the flag details; choose "✓ Reviewed", "— Ignore" or "🚨 Escalate", add an optional note, then "Confirm decision".\n'
                       'The flag leaves "Open" and the note stays visible on it for whoever comes next.'),
             'label': T('مراجعة', 'Review'),
             'open_hint': T('على كل إشارة «مفتوح».', 'On every "Open" flag.')},
            {'target': 'admin-audit-decision', 'label': T('✓ راجعت · — تجاهل · 🚨 تصعيد', '✓ Reviewed · — Ignore · 🚨 Escalate'),
             'text': T('قرارك على الإشارة، مع ملاحظة المراجعة ثم «تأكيد القرار».', 'Your decision on the flag, with a review note, then "Confirm decision".'),
             'warn': T('ماتتجاهلش من غير ما تفتح السجل وتتأكد — والملاحظة بتفضل متسجلة.', 'Do not ignore before checking the log — the note stays on record.'),
             'open_hint': T('اضغط «مراجعة» على إشارة.', 'Press "Review" on a flag.')},
            {'target': 'admin-audit-log-filters', 'text': T('في «سجل الإجراءات»: ابحث بالمستخدم أو الكيان وفلتر بنوع الإجراء، و«مسح».',
                                              'In "Action log": search by user or entity, filter by action type, and "Clear".'),
             'more': T('• البحث باسم المستخدم أو الكيان (زي رقم حجز).\n'
                       '• نوع الإجراء: إنشاء حجوزات، تغيير حالة، إلغاء، اعتماد تحويلات، دخول، محاولات فاشلة، مزامنة.\n'
                       'اضغط على أي سطر يفتح التغييرات قبل/بعد وعنوان IP. «مسح» بيرجّع الفلاتر.',
                       '• Search by user name or entity (such as a reservation number).\n'
                       '• Action type: reservations created, status changes, cancellations, transfer approvals, logins, failed attempts, sync.\n'
                       'Click any row to open the before/after changes and IP address. "Clear" resets the filters.'),
             'label': T('🔍 بحث · نوع الإجراء · مسح', '🔍 Search · action type · Clear'),
             'open_hint': _LOGS},
            {'target': 'admin-audit-log-table', 'label': T('سجل الإجراءات', 'Action log'),
             'text': T('الإجراء، المستخدم، الكيان والتوقيت. اضغط الصف يظهر التغييرات قبل وبعد وعنوان IP.',
                       'Action, user, entity and time. Click a row to see before/after changes and the IP address.'),
             'when': T('لما تحقق في «مين غيّر إيه».', 'When investigating "who changed what".'),
             'open_hint': _LOGS},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-30',
    },
]
