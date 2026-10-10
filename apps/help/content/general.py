from . import T

MODULE = {
    'key': 'general', 'group': 'home', 'icon': '◈',
    'title': T('الرئيسية والحساب', 'Home & account'),
    'summary': T(
        'الشاشات العامة التي يستخدمها كل الموظفين: الصفحة الرئيسية، لوحتك الشخصية، الإشعارات، '
        'الإعلانات الداخلية، أمان الحساب، ودليل الاستخدام نفسه.',
        'The screens every employee uses: the home page, your personal board, notifications, '
        'internal announcements, account security, and this help guide itself.'),
}

SCREENS = [
    {
        'key': 'general.dashboard',
        'routes': ['/dashboard'],
        'title': T('الرئيسية', 'Home dashboard'),
        'summary': T(
            'أول شاشة تظهر بعد الدخول. تعطيك صورة سريعة عن يوم العمل: الحجوزات النشطة ومسارها، '
            'متابعات الأدوية المزمنة المطلوبة اليوم، تنبيهات التحويلات، المخزون المنخفض، المبيعات، '
            'وحالة المزامنة مع SOFTECH. المحتوى يختلف حسب دورك وفرعك.',
            'The first screen after login. It gives a quick picture of the working day: active '
            'reservations and their pipeline, chronic follow-ups due today, transfer alerts, low stock, '
            'sales, and the SOFTECH sync status. What you see depends on your role and branch.'),
        'audience': T('كل الأدوار — كل دور يرى الأقسام التي تخصه.',
                      'All roles — each role sees the sections that concern it.'),
        'steps': [
            T('ابدأ يومك من شريط الأرقام العلوي: حجوزات نشطة، عاجلة، تنتظر اتصالاً، وما تم تسليمه هذا الأسبوع.',
              'Start your day from the top number strip: active, urgent, waiting-for-call and delivered-this-week reservations.'),
            T('اضغط «حجز جديد» من شريط الإجراءات السريعة لتسجيل طلب عميل فوراً.',
              'Press "New reservation" in the quick-action bar to record a customer request right away.'),
            T('راجع قسم «متابعة اليوم»: المرضى المزمنون الذين حان موعد صرفهم أو تأخروا — افتح أي صف لترى التفاصيل وتتواصل معهم.',
              'Check "Today\'s follow-ups": chronic patients whose refill is due or late — open a row to see details and contact them.'),
            T('لو ظهر «حجز عالق» (بدون تحديث أكثر من 7 أيام) اضغط «مراجعة» وحدّث حالته.',
              'If a "stuck reservation" appears (no update for more than 7 days), press "Review" and update its status.'),
            T('تابع «تنبيهات التحويل»: طلبات واردة لفرعك أو تحويلات تنتظر الرد أو لم تُصرف.',
              'Watch "Transfer alerts": requests coming to your branch, transfers waiting for a reply or not yet issued.'),
            T('أسفل الصفحة: تنبيهات المخزون المنخفض وحالة المزامنة مع SOFTECH وآخر وقت تحدّثت فيه البيانات.',
              'At the bottom: low-stock alerts, the SOFTECH sync status and when the data was last refreshed.'),
        ],
        'tips': [
            T('الأرقام هنا للمتابعة السريعة؛ اضغط على أي رقم أو قسم لتنتقل للشاشة التفصيلية.',
              'The numbers here are for quick monitoring; click any number or section to go to the detailed screen.'),
            T('لو حالة المزامنة «فشلت» أو آخر تحديث قديم، فالأرصدة قد لا تكون حديثة — بلّغ مسؤول النظام.',
              'If the sync shows "failed" or the last update is old, stock figures may be out of date — tell the system admin.'),
        ],
        'related': ['general.me', 'general.notifications'],
        'updated': '2026-10-10',
    },
    {
        'key': 'general.me',
        'routes': ['/me', '/m/me'],
        'title': T('لوحتي الشخصية', 'My personal board'),
        'summary': T(
            'لوحة خاصة بك وحدك تجمع بياناتك في SOFTECH من كل الأدوار التي تمارسها: كمورد، كعميل/موظف، '
            'وكمسؤول بيع (مبيعاتك، فواتيرك، أعلى أصنافك)، بالإضافة إلى مهامك التشغيلية المفتوحة. '
            'تختار أنت اللوحات (الويدجت) التي تظهر وترتيبها.',
            'A board just for you that gathers your SOFTECH data across every role you play: as a supplier, '
            'as a customer/employee, and as a salesperson (your sales, invoices, top items), plus your open '
            'operational tasks. You choose which widgets appear and in what order.'),
        'audience': T('كل الموظفين.', 'Every employee.'),
        'steps': [
            T('أول مرة: اضغط «هوياتي» ثم «المطالبة بهوية جديدة»، ابحث عن اسمك أو كودك في SOFTECH واطلب اعتماده.',
              'First time: press "My identities" then "Claim a new identity", search your name or code in SOFTECH and request approval.'),
            T('انتظر اعتماد المدير — الحالة تظهر «قيد المراجعة» ثم «معتمد». البيانات لا تظهر إلا لهوية معتمدة.',
              'Wait for a manager to approve — the status shows "Under review" then "Approved". Data only shows for an approved identity.'),
            T('اضغط «إضافة لوحة» واختر نوع البيانات (مبيعاتي، مستنداتي، حركات الخزينة، مهامي…) وعنواناً اختيارياً.',
              'Press "Add widget" and choose the data (my sales, my documents, cash movements, my tasks…) and an optional title.'),
            T('اسحب اللوحات لإعادة ترتيبها، واختر عرضها (عرض ١ / عرض ٢ / عرض كامل).',
              'Drag widgets to reorder them and choose their width (1 / 2 / full).'),
            T('في لوحة المستندات تستطيع تمييز المستند «كمُراجَع» أو كتابة ملاحظة تُحفظ في SOFTECH (المركز والفرع).',
              'In the documents widget you can mark a document as "reviewed" or write a note that is saved in SOFTECH (HQ and branch).'),
        ],
        'tips': [
            T('كل البيانات هنا محصورة على هويتك المعتمدة فقط — لا يمكن رؤية بيانات شخص آخر.',
              'All data here is limited to your own approved identity — nobody can see another person\'s data.'),
            T('لو ظهر «أحد السيرفرات غير متصل» فالحفظ في SOFTECH لم يكتمل في الفرع؛ أعد المحاولة لاحقاً.',
              'If "one of the servers is offline" appears, the SOFTECH save did not finish at the branch; try again later.'),
        ],
        'faq': [
            {'q': T('لماذا لوحتي فارغة؟', 'Why is my board empty?'),
             'a': T('إما لم تضف لوحات بعد، أو هويتك في SOFTECH لم تُعتمد. ابدأ من «هوياتي».',
                    'Either you have not added widgets yet, or your SOFTECH identity is not approved. Start from "My identities".')},
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'general.security',
        'routes': ['/security'],
        'title': T('أمان الحساب (المصادقة الثنائية)', 'Account security (two-factor)'),
        'summary': T(
            'تفعيل المصادقة الثنائية (TOTP) لحسابك: بعد كلمة المرور يطلب النظام رمزاً من تطبيق على موبايلك '
            '(مثل Google Authenticator). يحمي الحساب لو عرف أحد كلمة المرور.',
            'Turn on two-factor authentication (TOTP) for your account: after the password, the system asks for '
            'a code from an app on your phone (such as Google Authenticator). It protects the account if someone '
            'learns your password.'),
        'audience': T('كل الأدوار. أدوار الاعتماد (المدير، المشرف، المشتريات) ستكون ملزمة بها عند تفعيل الإلزام.',
                      'All roles. Approval roles (admin, supervisor, purchasing) will be required to use it once enforcement is on.'),
        'steps': [
            T('اضغط «تفعيل المصادقة الثنائية» وامسح رمز QR بتطبيق المصادقة على موبايلك.',
              'Press "Enable two-factor authentication" and scan the QR code with an authenticator app on your phone.'),
            T('اكتب الرمز المكوّن من 6 أرقام الذي يظهر في التطبيق لتأكيد التفعيل.',
              'Type the 6-digit code shown in the app to confirm.'),
            T('احفظ «رموز الاسترجاع» في مكان آمن — تستخدمها لو ضاع الموبايل.',
              'Keep the "recovery codes" somewhere safe — you use them if you lose your phone.'),
            T('للإيقاف: أدخل كلمة المرور ورمزاً حالياً أو رمز استرجاع.',
              'To turn it off: enter your password and a current code or a recovery code.'),
        ],
        'tips': [
            T('كل رمز استرجاع يُستخدم مرة واحدة فقط؛ الشاشة توضح كم رمزاً تبقّى.',
              'Each recovery code works once; the screen shows how many are left.'),
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'general.notifications',
        'routes': ['/notifications', '/m/notifications'],
        'title': T('الإشعارات', 'Notifications'),
        'summary': T(
            'صندوق كل الإشعارات التي وصلتك (حجوزات، توصيل، تحويلات، طلب ضائع، متابعات، مراقبة، تقارير، إشارات…) '
            'مع فلترة وتعليم كمقروء وتأجيل وحذف. الجرس أعلى الشاشة يعرض آخرها فقط، وهذه الصفحة تعرضها كلها.',
            'The inbox of every notification you received (reservations, delivery, transfers, lost demand, follow-ups, '
            'monitoring, reports, mentions…) with filters, mark-as-read, snooze and delete. The bell at the top shows '
            'only the latest; this page shows them all.'),
        'audience': T('كل المستخدمين.', 'Everyone.'),
        'steps': [
            T('اختر الفئة من القائمة أو فعّل «غير المقروء فقط» لترى المطلوب منك الآن.',
              'Pick a category or turn on "Unread only" to see what needs you now.'),
            T('اضغط على الإشعار لفتح السجل المرتبط به (حجز، تحويل…).',
              'Click a notification to open the record it refers to (reservation, transfer…).'),
            T('حدد عدة إشعارات ثم: تعليم كمقروء، تأجيل ساعة، أو حذف.',
              'Select several notifications, then: mark as read, snooze one hour, or delete.'),
            T('على الموبايل: فعّل «إشعارات المتصفح» لتصلك التنبيهات حتى والتطبيق مغلق.',
              'On the phone: turn on "Browser notifications" to get alerts even when the app is closed.'),
        ],
        'tips': [
            T('«التأجيل» يخفي الإشعار ساعة ثم يعيده — مفيد لما تحتاج تتصرف لاحقاً ولا تريد أن تنساه.',
              '"Snooze" hides the notification for an hour then brings it back — handy when you will act later and don\'t want to forget.'),
            T('لو رفضت إذن الإشعارات في المتصفح، فعّله من إعدادات المتصفح نفسه ثم ارجع هنا.',
              'If you denied notification permission in the browser, enable it from the browser settings then come back here.'),
        ],
        'related': ['general.announcements'],
        'updated': '2026-10-10',
    },
    {
        'key': 'general.announcements',
        'routes': ['/announcements'],
        'title': T('الإعلانات الداخلية', 'Internal announcements'),
        'summary': T(
            'تعميمات الإدارة للفروع (قرارات، تعليمات، تغييرات في العمل) مع «تأكيد القراءة»، '
            'حتى تتأكد الإدارة أن كل موظف قرأ التعميم.',
            'Management broadcasts to the branches (decisions, instructions, changes in work) with '
            '"acknowledge reading", so management knows every employee has read it.'),
        'audience': T('الجميع يقرأ؛ الإدارة تنشر وتتابع من قرأ.', 'Everyone reads; management publishes and tracks who read.'),
        'steps': [
            T('اقرأ الإعلان ثم اضغط «تأكيد القراءة» — هذا مطلوب ويُسجَّل باسمك.',
              'Read the announcement then press "Acknowledge" — this is required and recorded under your name.'),
            {'text': T('لنشر إعلان: «+ إعلان جديد» ← العنوان والنص ← اختر الأدوار والفروع المستهدفة (الفراغ = الجميع) ← «إعلان هام» لو عاجل ← «نشر الإعلان».',
                       'To publish: "+ New announcement" → title and text → choose target roles and branches (empty = everyone) → tick "Important" if urgent → "Publish".'),
             'roles': ['admin', 'supervisor']},
            {'text': T('اضغط «من قرأ» لترى قائمة من أكّد القراءة ونسبة القراءة.',
                       'Press "Who read" to see who acknowledged and the read rate.'),
             'roles': ['admin', 'supervisor']},
        ],
        'tips': [
            T('الإعلان الهام يصل أيضاً كإشعار على الجرس لكل المستهدفين.',
              'An important announcement also arrives as a bell notification to everyone targeted.'),
        ],
        'updated': '2026-10-10',
    },
    {
        'key': 'general.help_center',
        'routes': ['/help'],
        'title': T('دليل الاستخدام', 'Help guide'),
        'summary': T(
            'مكان واحد فيه شرح كل شاشات النظام: دور كل شاشة، طريقة استخدامها خطوة بخطوة، '
            'شرح كل تبويب، ودورة العمل الخاصة بكل موديول. يتحدّث مع كل ميزة جديدة.',
            'One place that explains every screen in the system: what each screen is for, how to use it step '
            'by step, what every tab does, and the workflow of each module. It is updated with every new feature.'),
        'audience': T('كل المستخدمين.', 'Everyone.'),
        'steps': [
            T('من أي شاشة اضغط زر «؟ مساعدة» أعلى الصفحة أو مفتاح F1 — يفتح شرح الشاشة التي أنت فيها، ويمكنك متابعة العمل والشرح مفتوح.',
              'From any screen press the "? Help" button at the top or the F1 key — it opens the help for the screen you are on, and you can keep working while it is open.'),
            T('لو الشاشة فيها تبويبات، الشرح يفتح على التبويب الذي تقف عليه ومكتوب بجانبه «أنت هنا».',
              'If the screen has tabs, the help opens on the tab you are on, marked "You are here".'),
            T('في هذه الصفحة تتصفح كل الموديولات أو تبحث بكلمة (عربي أو إنجليزي). يمكنك أيضاً البحث من Ctrl+K.',
              'On this page you can browse every module or search by a word (Arabic or English). You can also search from Ctrl+K.'),
            T('في آخر كل شرح اضغط «مفيد» أو «غير مفيد» واكتب ما ليس واضحاً — يصل للمدرب ليحسّن الشرح.',
              'At the end of any article press "Helpful" or "Not helpful" and write what is unclear — it reaches the trainer, who improves the text.'),
            {'text': T('للمدربين: افتح أي شرح واضغط «تعديل الشرح». التعديل يظهر للجميع فوراً ويُحفظ في السجل، ويمكن الرجوع للنسخة الأصلية في أي وقت.',
                       'For trainers: open any article and press "Edit help". The change shows to everyone immediately, is kept in the history, and can be reverted to the original at any time.'),
             'roles': ['admin', 'supervisor', 'quality_manager']},
        ],
        'tabs': [
            {'key': 'browse', 'title': T('تصفح الموديولات', 'Browse modules'),
             'body': T('كل موديولات النظام مقسّمة مثل القائمة الجانبية. اضغط موديول لترى دوره ودورة العمل وكل شاشاته، ثم اضغط شاشة لترى شرحها الكامل.',
                       'All modules grouped like the side menu. Click a module to see its role, its workflow and its screens, then click a screen for its full help.')},
            {'key': 'whats_new', 'title': T('الجديد', "What's new"),
             'body': T('الشاشات التي تغيّر شرحها مؤخراً (ميزة جديدة أو تعديل)، الأحدث أولاً. علامة «جديد» تعني أنك لم تقرأ النسخة الحالية بعد.',
                       'Screens whose help changed recently (a new feature or change), newest first. A "New" badge means you have not read the current version yet.')},
            {'key': 'trainers', 'title': T('للمدربين', 'For trainers'),
             'body': T('يظهر لمن لديه صلاحية تعديل الشرح: أكثر الشاشات التي يُفتح شرحها، تقييمات الشرح، ما يبحث عنه المستخدمون (وما لم يجدوا له نتيجة)، والملاحظات المفتوحة. استخدمها لتعرف أين يحتاج الفريق تدريباً.',
                       'For those allowed to edit help: the screens whose help is opened most, ratings, what users search for (and what found nothing), and open comments. Use it to see where the team needs training.')},
        ],
        'tips': [
            T('نقطة صفراء على زر المساعدة تعني أن شرح هذه الشاشة تغيّر منذ آخر مرة قرأته.',
              'A yellow dot on the help button means this screen\'s help changed since you last read it.'),
            T('يمكنك قراءة الشرح بالإنجليزي حتى لو الشاشة بالعربي — زر «ع / EN» داخل لوحة المساعدة.',
              'You can read the help in English even when the screen is in Arabic — the "ع / EN" switch is inside the help panel.'),
            T('صلاحية تعديل الشرح تُمنح من «مصفوفة الصلاحيات» على موديول «دليل الاستخدام» (إجراء تعديل).',
              'Permission to edit help is granted in the "Permissions matrix" on the "Help guide" module (edit action).'),
        ],
        'updated': '2026-10-10',
    },
]
