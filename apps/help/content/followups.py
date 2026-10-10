from . import T

MODULE = {
    'key': 'followups', 'group': 'operations', 'icon': '💊',
    'title': T('متابعة المرضى المزمنين', 'Chronic patient follow-up'),
    'summary': T(
        'النظام يحسب لكل مريض مزمن موعد نفاد دوائه من تاريخ آخر صرف ومعدل الاستخدام، ويُنشئ «مهمة متابعة» قبل الموعد '
        'حتى نتصل به أو نراسله واتساب ونجهّز له الدواء (في الفرع أو توصيل). لو اشترى المريض فعلاً تُغلق المهمة تلقائياً '
        'عندما تؤكد SOFTECH البيع. يوجد أيضاً تذكير واتساب يومي تلقائي (عند تفعيله) يتيح للعميل اختيار التجهيز في الفرع أو التوصيل.',
        'For every chronic patient the system calculates when their medicine runs out from the last dispense date and the usage rate, '
        'and creates a "follow-up task" before that date so we call or WhatsApp them and prepare the medicine (at the branch or delivered). '
        'If the patient actually buys, the task closes automatically when SOFTECH confirms the sale. There is also an automatic daily '
        'WhatsApp reminder (when enabled) that lets the customer choose branch pickup or delivery.'),
    'workflows': [
        {
            'title': T('مراحل مهمة المتابعة', 'Follow-up task stages'),
            'model': 'followups.FollowUpTask', 'field': 'status',
            'states': [
                {'key': 'pending', 'label': T('معلق — لم يُتواصل بعد', 'Pending — not contacted'),
                 'desc': T('المهمة جاهزة ولم يتصل أحد. ابدأ بالمتأخر والأعلى أولوية.', 'Ready and nobody has called yet. Start with overdue and highest priority.'),
                 'next': ['called', 'done', 'missed', 'cancelled', 'auto_closed']},
                {'key': 'called', 'label': T('تم الاتصال — لا رد', 'Called — no answer'),
                 'desc': T('حاولنا ولم يرد. حاول مرة أخرى أو أرسل واتساب.', 'We tried and got no answer. Try again or send WhatsApp.'),
                 'next': ['done', 'missed', 'cancelled', 'auto_closed']},
                {'key': 'done', 'label': T('مكتمل — تم الشراء', 'Done — purchased'),
                 'desc': T('المريض أكّد أو اشترى. مرحلة نهائية.', 'The patient confirmed or bought. Final.')},
                {'key': 'missed', 'label': T('فائت — لا استجابة', 'Missed — no response'),
                 'desc': T('لم يستجب بعد عدة محاولات. مرحلة نهائية.', 'No response after several attempts. Final.')},
                {'key': 'auto_closed', 'label': T('أُغلق تلقائياً — SOFTECH أكّد البيع', 'Auto-closed — SOFTECH confirmed the sale'),
                 'desc': T('ظهرت فاتورة بيع جديدة للمريض لنفس الدواء، فأُغلقت المهمة بدون تدخل.', 'A new sale of the same medicine appeared for the patient, so the task closed by itself.')},
                {'key': 'cancelled', 'label': T('ملغي', 'Cancelled'), 'desc': T('لم تعد مطلوبة (مثلاً الطبيب أوقف الدواء).', 'No longer needed (e.g. the doctor stopped the medicine).')},
            ],
        },
        {
            'title': T('تذكير الصرف عبر واتساب', 'WhatsApp refill reminder'),
            'model': 'followups.RefillReminder', 'field': 'status',
            'intro': T('رسالة واحدة لكل عميل قبل موعد صرفه. ردّه يُنشئ حجزاً تلقائياً (تجهيز في الفرع أو توصيل) أو يوقف التذكيرات.',
                       'One message per customer before their refill date. Their reply automatically creates a reservation (branch pickup or delivery) or stops reminders.'),
            'states': [
                {'key': 'sent', 'label': T('أُرسل', 'Sent'), 'desc': T('وصلت الرسالة وننتظر الرد.', 'Delivered; waiting for a reply.'), 'next': ['replied']},
                {'key': 'replied', 'label': T('ردّ العميل', 'Replied'),
                 'desc': T('اختار: تجهيز في الفرع، توصيل للمنزل، أو إيقاف التذكيرات. الصيدلي يؤكد الأصناف قبل التجهيز.',
                           'They chose: branch pickup, home delivery, or stop reminders. A pharmacist confirms the items before preparing.')},
                {'key': 'failed', 'label': T('فشل الإرسال', 'Failed'), 'desc': T('لم تُرسل (رقم خاطئ أو مشكلة اتصال).', 'Not sent (wrong number or a connection problem).')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'followups.tasks',
        'routes': ['/followups'],
        'title': T('متابعة المزمن', 'Chronic follow-ups'),
        'summary': T(
            'قائمة مهام متابعة المرضى المزمنين: من حان موعد صرفه أو تأخر، مع بيانات العميل وقيمته وخطر انقطاعه، الدواء، '
            'تاريخ آخر صرف وموعد الاستحقاق، والمكملات المقترحة. منها تتصل أو ترسل واتساب وتسجّل النتيجة.',
            'The list of chronic patient follow-up tasks: who is due or overdue, with the customer\'s value and churn risk, the medicine, '
            'last dispense and due date, and suggested complementary items. From here you call or WhatsApp and record the outcome.'),
        'audience': T('مركز الاتصال والصيادلة والمندوبون والمشرفون.', 'Call center, pharmacists, salespeople and supervisors.'),
        'tabs': [
            {'key': 'all', 'title': T('كل المهام', 'All tasks'), 'body': T('كل المهام حسب الفلاتر المختارة.', 'All tasks matching the filters.')},
            {'key': 'mine', 'title': T('👤 معينة لي', '👤 Assigned to me'), 'body': T('المهام المسندة لك أنت (أو لدورك/فرعك). ابدأ يومك من هنا.', 'Tasks assigned to you (or your role/branch). Start your day here.')},
            {'key': 'pinned', 'title': T('📌 المثبتة', '📌 Pinned'), 'body': T('مهام ثبّتها للمتابعة الشخصية (اضغط الدبوس على أي مهمة).', 'Tasks you pinned for personal follow-up (press the pin on any task).')},
            {'key': 'untracked', 'title': T('🔔 غير متابعة', '🔔 Not followed'), 'body': T('مهام لم يتابعها أحد بعد — لا يجب أن تبقى هنا طويلاً.', 'Tasks nobody has followed yet — they should not stay here long.')},
            {'key': 'priority', 'title': T('⚡ الأعلى أولوية', '⚡ Highest priority'), 'body': T('مرتبة بدرجة الأولوية (قيمة العميل، التأخير، خطر الانقطاع).', 'Sorted by priority score (customer value, delay, churn risk).')},
            {'key': 'overview', 'title': T('📋 ملخص (داخل المهمة)', '📋 Summary (inside a task)'),
             'body': T('بيانات العميل والهاتف (إن كان مسموحاً لك برؤيته)، الدواء، آخر صرف وموعد الاستحقاق، رقم مستند SOFTECH، و«تسجيل النتيجة».',
                       'Customer data and phone (if you may see it), the medicine, last dispense and due date, the SOFTECH document number, and "Record outcome".')},
            {'key': 'product', 'title': T('💊 المنتج', '💊 Product'),
             'body': T('تفاصيل الدواء: الاستخدام، الشكل، حجم العبوة، المادة الفعالة، السعر، ومتوسط الاستهلاك اليومي ومدة العبوة.',
                       'Medicine details: indication, form, pack size, active ingredient, price, average daily use and how long a pack lasts.')},
            {'key': 'whatsapp', 'title': T('💬 واتساب', '💬 WhatsApp'),
             'body': T('رسالة واتساب جاهزة يمكنك تعديلها قبل الإرسال، ويمكن إضافة توصيات تكميلية لها.', 'A ready WhatsApp message you can edit before sending, optionally with complementary suggestions.')},
            {'key': 'cross_sell', 'title': T('🛒 مكمّلات', '🛒 Complementary'),
             'body': T('أصناف تُشترى عادةً مع هذا الدواء لاقتراحها على العميل.', 'Items usually bought with this medicine, to suggest to the customer.')},
            {'key': 'history', 'title': T('📞 السجل', '📞 History'),
             'body': T('سجل المكالمات والرسائل والملاحظات السابقة مع هذا العميل.', 'Previous calls, messages and notes with this customer.')},
        ],
        'steps': [
            T('اختر التبويب الشخصي («معينة لي» عادةً) وشريحة الحالة (المتأخرة أولاً).', 'Pick a personal tab ("Assigned to me" usually) and a status chip (overdue first).'),
            T('اعرض «قائمة» أو «مجمّع بالعميل» — المجمّع يجمع كل أدوية العميل في بطاقة واحدة لتتصل مرة واحدة.',
              'View as "List" or "Grouped by customer" — grouped puts all a customer\'s medicines on one card so you call once.'),
            T('افتح المهمة واتصل، أو «إرسال واتساب» (يمكنك اختيار أدوية بعينها للرسالة).', 'Open the task and call, or "Send WhatsApp" (you can choose specific medicines for the message).'),
            T('«تسجيل النتيجة»: اختر النتيجة (اشترى/أكّد، أكّد الحضور للفرع، طلب توصيل، سيتصل لاحقاً، الصنف غير متوفر، اشترى من مكان آخر، الطبيب غيّر الدواء، الرقم خاطئ…).',
              '"Record outcome": choose the result (bought/confirmed, will come to branch, delivery request, will call later, item unavailable, bought elsewhere, doctor changed the medicine, wrong number…).'),
            {'text': T('للمشرف: حدد مهاماً ثم «إسناد إلى» موظف أو دور أو فرع، مع معاينة من سيستلمها.',
                       'Supervisors: select tasks then "Assign to" an employee, role or branch, with a preview of who will get them.'),
             'roles': ['admin', 'supervisor']},
        ],
        'tips': [
            T('الهاتف يظهر محجوباً (●●●) لو دورك لا يسمح برؤيته؛ في هذه الحالة زر واتساب لا يظهر.',
              'The phone appears masked (●●●) if your role may not see it; then the WhatsApp button is hidden.'),
            T('لا تغلق المهمة «مكتمل» إلا لو العميل اشترى أو أكد فعلاً؛ لو اشترى من فرع آخر ستُغلق تلقائياً.',
              'Only mark a task "Done" if the customer bought or really confirmed; if they bought at another branch it closes automatically.'),
        ],
        'related': ['followups.reminders', 'customers.detail', 'chronic.classifier'],
        'updated': '2026-10-10',
    },
    {
        'key': 'followups.reminders',
        'routes': ['/followups/reminders'],
        'title': T('تذكيرات الصرف عبر واتساب', 'WhatsApp refill reminders'),
        'summary': T(
            'مراجعة التذكيرات اليومية التلقائية: ما أُرسل، من ردّ وماذا اختار (تجهيز في الفرع، توصيل، إيقاف)، والحجوزات التي أُنشئت من الردود، '
            'مع معاينة «التشغيل القادم» وسبب استبعاد أي عميل. الإرسال الفعلي يُفعَّل من إعدادات النظام؛ عندما يكون متوقفاً تعمل الشاشة كمعاينة فقط.',
            'Review of the automatic daily reminders: what was sent, who replied and what they chose (branch pickup, delivery, stop), and reservations created from replies, '
            'with a preview of the "next run" and why any customer is skipped. Actual sending is switched on in system settings; when off, the screen is a preview only.'),
        'audience': T('مركز الاتصال والمشرفون.', 'Call center and supervisors.'),
        'steps': [
            T('راجع المؤشرات: أُرسل خلال 30 يوماً، نسبة الرد، تجهيز في الفرع، توصيل، حجوزات أُنشئت، فشل، وأوقفوا التذكيرات.',
              'Check the numbers: sent in 30 days, reply rate, branch pickup, delivery, reservations created, failed, and opted out.'),
            T('«سجل التذكيرات»: كل رسالة وحالتها ورد العميل والحجز الناتج.', '"Reminder log": every message, its status, the reply and the resulting reservation.'),
            T('«التشغيل القادم»: من سيصله تذكير ومن لن يصله ولماذا.', '"Next run": who will get a reminder and who will not, and why.'),
            {'text': T('«تشغيل الآن» يرسل دفعة اليوم فوراً (عند تفعيل الإرسال).', '"Run now" sends today\'s batch immediately (when sending is enabled).'),
             'roles': ['admin', 'supervisor']},
        ],
        'tips': [
            T('الرسالة لا تذكر اسم الدواء (خصوصية المريض)؛ الصيدلي يؤكد الأصناف عند التجهيز.',
              'The message does not name the medicine (patient privacy); the pharmacist confirms the items when preparing.'),
        ],
        'related': ['followups.tasks', 'reservations.board'],
        'updated': '2026-10-10',
    },
]
