from . import T

MODULE = {
    'key': 'hr', 'group': 'hr', 'icon': '👥',
    'title': T('الموارد البشرية والموافقات والجودة', 'HR, approvals & quality'),
    'summary': T(
        'طلبات الموظفين (إجازة، إذن مأمورية أو تعديل شيفت، ساعات إضافية، سلفة، مطالبة مصروفات) تمر بمحرك موافقات موحّد: كل نوع طلب له خطوات اعتماد محددة '
        '(دور معيّن أو شخص، وقد تكون مقصورة على فرع الطالب)، والقرار من «صندوق الموافقات». ومعها الحضور والانصراف بالموقع (GPS) ومراجعات الجودة للفروع من الموبايل.',
        'Employee requests (leave, errand or shift-change permit, overtime, salary advance, expense claim) go through one approval engine: each request type has defined approval steps '
        '(a role or a named person, possibly limited to the requester\'s branch), decided from the "Approvals inbox". Plus GPS clock in/out and branch quality inspections on the phone.'),
    'workflows': [{
        'title': T('مراحل طلب الموافقة', 'Approval request stages'),
        'model': 'approvals.ApprovalRequest', 'field': 'status',
        'states': [
            {'key': 'draft', 'label': T('مسودة', 'Draft'), 'desc': T('لم يُقدَّم بعد.', 'Not submitted yet.'), 'next': ['pending', 'cancelled']},
            {'key': 'pending', 'label': T('في الانتظار', 'Pending'), 'desc': T('ينتظر المعتمد في الخطوة الحالية.', 'Waiting for the approver at the current step.'), 'next': ['in_review', 'approved', 'rejected', 'cancelled', 'expired']},
            {'key': 'in_review', 'label': T('قيد المراجعة', 'In review'), 'desc': T('اعتُمدت خطوة وينتقل للخطوة التالية.', 'A step was approved; moving to the next step.'), 'next': ['approved', 'rejected', 'expired']},
            {'key': 'approved', 'label': T('معتمد', 'Approved'), 'desc': T('اعتُمد في كل الخطوات.', 'Approved at every step.')},
            {'key': 'rejected', 'label': T('مرفوض', 'Rejected'), 'desc': T('رُفض في إحدى الخطوات (مع سبب).', 'Rejected at a step (with a reason).')},
            {'key': 'cancelled', 'label': T('ملغي', 'Cancelled'), 'desc': T('ألغاه مقدّمه.', 'Cancelled by the requester.')},
            {'key': 'expired', 'label': T('منتهي الصلاحية', 'Expired'), 'desc': T('تجاوز الوقت المسموح للقرار.', 'Passed the allowed decision time.')},
        ],
    }],
    'flows': [
        {
            'key': 'request',
            'title': T('طلب إجازة أو إذن', 'A leave or permission request'),
            'summary': T('إزاي تقدّم طلب وتتابع حالته لحد القرار.',
                         'How to submit a request and follow it until a decision.'),
            'steps': [
                {'target': 'nav-hr', 'nav': '/hr',
                 'text': T('«الإجازات والطلبات» من القائمة.',
                           '"Leave & requests" from the menu.'),
                 'more': T('دي الشاشة اللي كل موظف بيقدّم منها طلباته، أياً كان دوره.\n'
                           '• من هنا بتطلب إجازة أو إذن أو إضافي أو سلفة أو مصروفات.\n'
                           '• كل طلب تقدّمه بيروح لوحده لمسار الموافقات، والمعتمد بيشوفه في «صندوق الموافقات».',
                           'This is the screen every employee submits requests from, whatever their role.\n'
                           '• From here you request leave, a permit, overtime, an advance or expenses.\n'
                           '• Every request you submit goes to the approval flow by itself, and the approver sees it in the "Approvals inbox".')},
                {'target': 'hr-requests-tabs', 'route': '/hr',
                 'text': T('اختار نوع الطلب: إجازة، إذن، إضافي، سلفة، مصروف.',
                           'Choose the request type: leave, permission, overtime, advance, expense.'),
                 'more': T('كل تبويب له نموذج وجدول خاص بيه:\n'
                           '• «الإجازات» و«الأذونات» (مأمورية أو تعديل شيفت) و«الإضافي».\n'
                           '• «السلف» على الراتب و«المصروفات» (مواصلات، وجبات، مأمورية…).\n'
                           'اختار التبويب الصح الأول، عشان كل نوع له حقوله وخطوات اعتماده.',
                           'Each tab has its own form and table:\n'
                           '• "Leave", "Permits" (errand or shift change) and "Overtime".\n'
                           '• Salary "Advances" and "Expenses" (transport, meals, errand…).\n'
                           'Pick the right tab first, because each type has its own fields and approval steps.')},
                {'target': 'hr-requests-balances', 'route': '/hr',
                 'text': T('رصيد إجازاتك المتبقي.',
                           'Your remaining leave balance.'),
                 'more': T('بطاقة لكل نوع إجازة: الأيام المتبقية من إجمالي المستحق في السنة.\n'
                           'بصّ عليها قبل ما تطلب، عشان تعرف عندك كام يوم.\n'
                           'البطاقات بتظهر بس لو ليك أرصدة مسجّلة.',
                           'A card per leave type: the days left out of the yearly entitlement.\n'
                           'Check it before you request, so you know how many days you have.\n'
                           'The cards only show if balances are recorded for you.')},
                {'target': 'hr-requests-new', 'route': '/hr',
                 'text': T('اضغط «+ طلب إجازة جديد» يفتح النموذج.',
                           'Click "+ New leave request" to open the form.'),
                 'more': T('الزرار بيفتح نموذج الطلب تحت الأرصدة مباشرة، ولو ضغطته تاني بيقفله.\n'
                           'فتح النموذج مش بيسجّل أي حاجة — الطلب مش بيتحفظ غير بـ«تقديم الطلب».',
                           'The button opens the request form right under the balances; pressing it again closes it.\n'
                           'Opening the form saves nothing — the request is only saved with "Submit request".')},
                {'target': 'hr-requests-form', 'route': '/hr',
                 'text': T('النوع والتواريخ والسبب.',
                           'Type, dates and reason.'),
                 'more': T('اختار نوع الإجازة والسبب، ومن تاريخ لتاريخ وعدد الأيام ويوم العودة (اسم اليوم بيظهر تحت التاريخ).\n'
                           '• «الطلب باسم»: نفسك، أو زميل، أو موظف بدون حساب.\n'
                           '• «كود الموارد البشرية» إجباري.\n'
                           '• «المعتمِدون المختارون»: يكفي اعتماد واحد منهم، وموافقة المدير المباشر مطلوبة دايماً.',
                           'Choose the leave type and reason, from–to dates, number of days and return date (the weekday shows under the date).\n'
                           '• "Request for": yourself, a colleague, or an employee without an account.\n'
                           '• "HR code" is required.\n'
                           '• "Chosen approvers": one of them approving is enough, and the direct manager\'s approval is always required.')},
                {'target': 'hr-requests-submit', 'route': '/hr',
                 'text': T('«تقديم الطلب» يبعته لمسار الموافقات. (في الجولة مش هنقدّم.)',
                           '"Submit request" sends it to the approval flow. (In this tour we will not submit.)'),
                 'more': T('بيحفظ الطلب ويبعته للمعتمد في أول خطوة، والنموذج بيتقفل والطلب يظهر في الجدول «بانتظار الموافقة».\n'
                           'لو فيه حقل ناقص أو غلط، رسالة الخطأ بتظهر فوق الزرار والطلب مش بيتسجّل.',
                           'It saves the request and sends it to the first-step approver; the form closes and the request shows in the table as "Awaiting approval".\n'
                           'If a field is missing or wrong, the error shows above the button and nothing is saved.')},
                {'target': 'hr-requests-table', 'route': '/hr',
                 'text': T('طلباتك وحالتها — الحالة بتتغير مع كل قرار وبيوصلك إشعار.',
                           'Your requests and their status — it changes with each decision and you are notified.'),
                 'more': T('هنا بتتابع كل طلب لحد القرار النهائي.\n'
                           '• لما يتعتمد أو يترفض بيوصلك إشعار والحالة تتغير هنا.\n'
                           '• 🖨️ بتطبع الطلب، و«إلغاء» متاح بس طول ما الطلب مسودة أو بانتظار الموافقة.',
                           'Here you follow each request until the final decision.\n'
                           '• When it is approved or rejected you get a notification and the status changes here.\n'
                           '• 🖨️ prints the request; "Cancel" is only available while it is a draft or awaiting approval.')},
            ],
        },
        {
            'key': 'approvals',
            'title': T('الموافقة على طلبات الفريق', 'Approving the team\'s requests'),
            'summary': T('فين تلاقي الطلبات اللي مستنية قرارك، وإزاي تقرر.',
                         'Where to find requests waiting for your decision, and how to decide.'),
            'roles': ['admin', 'supervisor', 'pharmacist', 'quality_manager', 'purchasing'],
            'steps': [
                {'target': 'nav-approvals', 'nav': '/approvals',
                 'text': T('«صندوق الموافقات» من القائمة.',
                           '"Approvals inbox" from the menu.'),
                 'more': T('صندوق واحد لكل الطلبات اللي مستنية قرارك: طلبات الموظفين، وعزل الدفعات، وغيرها.\n'
                           'بيظهر في القائمة للأدوار اللي بتعتمد حاجة، ولما طلب يوصل لخطوتك بيجيلك إشعار.',
                           'One inbox for every request waiting for your decision: employee requests, batch quarantine and more.\n'
                           'It shows in the menu for roles that approve something, and you are notified when a request reaches your step.')},
                {'target': 'hr-approvals-tabs', 'route': '/approvals',
                 'text': T('«بانتظار القرار» للجديد، و«السجل» للطلبات المقفولة.',
                           '"Awaiting decision" for new ones, "History" for closed requests.'),
                 'more': T('• «بانتظار القرار»: الطلبات اللي الخطوة الحالية فيها عندك، ومنها بتقرر.\n'
                           '• «السجل»: الطلبات اللي اتقفلت (معتمد، مرفوض، ملغى، منتهي الصلاحية) — للعرض بس.',
                           '• "Awaiting decision": requests whose current step is yours; you decide from here.\n'
                           '• "History": closed requests (approved, rejected, cancelled, expired) — view only.')},
                {'target': 'hr-approvals-table', 'route': '/approvals',
                 'text': T('الطلبات اللي عليها الدور عندك في مسار الموافقة.',
                           'The requests whose current approval step is yours.'),
                 'more': T('لكل طلب: العنوان، النوع (مسار الموافقة)، مقدّم الطلب، الحالة والتاريخ.\n'
                           'لو الصندوق فاضي هتلاقي «لا توجد طلبات بانتظار القرار».',
                           'For each request: title, type (approval flow), requester, status and date.\n'
                           'If the inbox is empty you see "No requests awaiting decision".')},
                {'target': 'hr-approvals-decide', 'route': '/approvals',
                 'text': T('«اتخاذ قرار»: موافقة أو رفض مع ملاحظة — بيتسجّل وبيوصل لمقدّم الطلب.',
                           '"Decide": approve or reject with a note — it is recorded and reaches the requester.'),
                 'more': T('بيفتح نافذة: اختار «✅ موافقة» أو «❌ رفض»، واكتب ملاحظة (اختيارية بس مهمة مع الرفض)، وبعدين «تأكيد القرار».\n'
                           '• لو فيه خطوة تالية الطلب بيروح لمعتمدها، ولو دي الأخيرة مقدّم الطلب بيوصله إشعار بالنتيجة.\n'
                           '• السيرفر بيتأكد إنك المعتمد الصح للخطوة دي.',
                           'It opens a window: choose "✅ Approve" or "❌ Reject", add a note (optional, but important when rejecting), then "Confirm decision".\n'
                           '• If there is a next step the request moves to its approver; if this was the last, the requester is notified of the result.\n'
                           '• The server checks you are the right approver for this step.')},
            ],
        },
        {
            'key': 'mobile_approvals',
            'title': T('الموافقات من الموبايل', 'Approvals on mobile'),
            'summary': T('قرّر الطلبات من الموبايل.',
                         'Decide requests on mobile.'),
            'roles': ['admin', 'supervisor', 'purchasing'],
            'mobile': True,
            'steps': [
                {'target': 'mshell-tabs',
                 'text': T('الشاشات في الشريط اللي تحت. اللي مش ظاهر تلاقيه في «المزيد».',
                           'Screens are in the bottom bar. Anything not shown is under "More".'),
                 'more': T('على الموبايل التنقل كله من الشريط اللي تحت.\n'
                           '«الموافقات» بتظهر للمدير والمشرف والمشتريات، ولو مش في الشريط هتلاقيها في «المزيد».',
                           'On the phone all navigation is from the bottom bar.\n'
                           '"Approvals" shows for admins, supervisors and purchasing; if it is not in the bar, find it under "More".')},
                {'target': 'hr-mobile-approvals-tabs', 'route': '/m/approvals',
                 'text': T('«تشغيلية» أو «HR».',
                           '"Operational" or "HR".'),
                 'more': T('• «تشغيلية»: الموافقات التشغيلية + طلبات تغيير السعر/الخصم.\n'
                           '• «HR»: إجازات، أذونات، إضافي، سلف، مصروفات.\n'
                           'بدّل بينهم عشان تخلّص كل نوع لوحده.',
                           '• "Operational": operational approvals + price/discount change requests.\n'
                           '• "HR": leave, permits, overtime, advances, expenses.\n'
                           'Switch between them to clear each kind on its own.')},
                {'target': 'hr-mobile-approvals-list', 'route': '/m/approvals',
                 'text': T('الطلبات من الأحدث.',
                           'The requests, newest first.'),
                 'more': T('كل كارت فيه عنوان الطلب وتفاصيله، والخطوة الحالية، ومقدّم الطلب وإمتى اتقدّم.\n'
                           'في طلبات تغيير السعر هتلاقي القيمة القديمة ← الجديدة والسبب.',
                           'Each card shows the request title and details, the current step, the requester and when it was submitted.\n'
                           'For price changes you see the old → new value and the reason.')},
                {'target': 'hr-mobile-approvals-tag', 'route': '/m/approvals',
                 'text': T('نوع الطلب، و«متأخر» لو عدّى موعده.',
                           'The request type, and "Overdue" when late.'),
                 'more': T('الشارة بتقول نوع الطلب (مسار الموافقة أو «تغيير سعر/خصم»).\n'
                           'كلمة «متأخر» بالأحمر معناها إن الطلب عدّى المهلة المحددة للقرار — ابدأ بيه.',
                           'The badge shows the request type (approval flow, or "Price/discount change").\n'
                           'A red "Overdue" means the request passed its decision deadline — start with it.')},
                {'target': 'hr-mobile-approvals-decide', 'route': '/m/approvals',
                 'text': T('«اعتماد» أو «رفض» مع ملاحظة — حسب صلاحيتك وبيتسجّل.',
                           '"Approve" or "Reject" with a note — per your permission; it is recorded.'),
                 'more': T('الضغط بيفتح نافذة تأكيد من تحت فيها ملاحظة (سبب الرفض مستحسن)، والقرار مش بيتنفذ غير بـ«تأكيد».\n'
                           'بعدها الطلب بيختفي من القائمة، ولو السيرفر رفض (مش صلاحيتك مثلاً) الرسالة بتظهر في النافذة.',
                           'Tapping opens a confirmation sheet with a note (a rejection reason is recommended); nothing happens until "Confirm".\n'
                           'Then the request leaves the list; if the server refuses (not your permission, for example) the message shows in the sheet.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'hr.requests',
        'routes': ['/hr'],
        'title': T('الموارد البشرية', 'Human resources'),
        'summary': T('تقديم ومتابعة طلبات الموظفين وطباعتها. كل طلب يُقدَّم يذهب تلقائياً لمسار الموافقات.', 'Submit, follow and print employee requests. Every submitted request goes to the approval flow automatically.'),
        'audience': T('كل الموظفين (طلباتهم)، والمديرون (طلبات فرقهم).', 'Every employee (their own requests), and managers (their teams\').'),
        'tabs': [
            {'key': 'leave', 'title': T('🏖️ الإجازات', '🏖️ Leave'), 'body': T('طلب إجازة: النوع، السبب، من-إلى وعدد الأيام وتاريخ العودة. يظهر رصيدك المتبقي لكل نوع.', 'A leave request: type, reason, from–to, number of days and return date. Your remaining balance per type is shown.')},
            {'key': 'permits', 'title': T('📝 الأذونات', '📝 Permits'), 'body': T('إذن مأمورية أو إذن تعديل شيفت: التاريخ، من الساعة حتى الساعة، والجهة.', 'An errand or shift-change permit: date, from–to time, and the destination.')},
            {'key': 'overtime', 'title': T('⏱️ الإضافي', '⏱️ Overtime'), 'body': T('طلب ساعات إضافية: التاريخ وعدد الساعات والسبب.', 'An overtime request: date, hours and reason.')},
            {'key': 'advances', 'title': T('💵 السلف', '💵 Advances'), 'body': T('طلب سلفة على الراتب: المبلغ وتاريخ السداد والسبب.', 'A salary advance: amount, repayment date and reason.')},
            {'key': 'expenses', 'title': T('🧾 المصروفات', '🧾 Expenses'), 'body': T('مطالبة مصروفات (مواصلات، وجبات، إقامة، قرطاسية، معدات، مأمورية…) ولو مأمورية: الوجهة والغرض والمغادرة والعودة والمسافة والبدل.', 'An expense claim (transport, meals, lodging, stationery, equipment, errand…) and for an errand: destination, purpose, departure, return, distance and allowance.')},
        ],
        'tips': [T('الطلب «المسودة» لا يصل لأحد — قدّمه.', 'A "draft" request reaches nobody — submit it.')],
        'related': ['hr.approvals', 'hr.attendance'],
        'tour': [
            {'target': 'hr-requests-tabs', 'text': T('نوع الطلب: إجازات، أذونات، إضافي، سلف، مصروفات.',
                                              'Request type: leave, permissions, overtime, advances, expenses.'),
             'more': T('كل تبويب له نموذج وجدول طلبات خاص بيه.\n'
                       '• «الأذونات»: إذن مأمورية (لازم الجهة) أو إذن تعديل شيفت، بالتاريخ ومن الساعة لحد الساعة.\n'
                       '• «المصروفات»: لو الفئة «مأمورية» بتظهر حقول الوجهة والمغادرة والعودة والمسافة والبدل.',
                       'Each tab has its own form and request table.\n'
                       '• "Permits": an errand permit (destination required) or a shift-change permit, with date and from–to time.\n'
                       '• "Expenses": if the category is "Errand", fields for destination, departure, return, distance and allowance appear.')},
            {'target': 'hr-requests-balances', 'text': T('رصيد إجازاتك المتبقي.',
                                              'Your remaining leave balance.'),
             'more': T('بطاقة لكل نوع إجازة فيها الأيام المتبقية من المستحق في السنة.\n'
                       'راجعها قبل ما تطلب إجازة عشان تعرف رصيدك. البطاقات بتظهر بس لو ليك أرصدة مسجّلة.',
                       'A card per leave type with the days left out of the yearly entitlement.\n'
                       'Check it before requesting leave so you know your balance. The cards only show if balances are recorded for you.')},
            {'target': 'hr-requests-new', 'text': T('«+ طلب إجازة جديد» يفتح النموذج.',
                                              '"+ New leave request" opens the form.'),
             'more': T('بيفتح نموذج الطلب تحت الأرصدة، والضغط تاني بيقفله.\n'
                       'في التبويبات التانية هتلاقي زرار مشابه: «+ إذن جديد»، «+ طلب إضافي جديد»، «+ طلب سلفة جديدة»، «+ مطالبة جديدة».',
                       'It opens the request form under the balances; pressing again closes it.\n'
                       'Other tabs have a similar button: "+ New permit", "+ New overtime request", "+ New advance request", "+ New claim".')},
            {'target': 'hr-requests-form', 'text': T('اختار النوع والتواريخ والسبب.',
                                              'Choose the type, dates and reason.'),
             'more': T('املا نوع الإجازة والسبب والتواريخ وعدد الأيام ويوم العودة.\n'
                       '• «الطلب باسم»: نفسك أو زميل أو موظف بدون حساب (وقتها اكتب اسمه).\n'
                       '• «كود الموارد البشرية» إجباري.\n'
                       '• اختار «المعتمِدون»: يكفي اعتماد واحد منهم، وموافقة المدير المباشر مطلوبة دايماً.',
                       'Fill the leave type, reason, dates, number of days and return date.\n'
                       '• "Request for": yourself, a colleague or an employee without an account (then type their name).\n'
                       '• "HR code" is required.\n'
                       '• Choose "Approvers": one of them approving is enough; the direct manager\'s approval is always required.')},
            {'target': 'hr-requests-submit', 'text': T('«تقديم الطلب» يبعته لمسار الموافقات.',
                                              '"Submit request" sends it to the approval flow.'),
             'more': T('بيحفظ الطلب ويبعته للمعتمد في أول خطوة، والنموذج بيتقفل والطلب يظهر في الجدول «بانتظار الموافقة».\n'
                       'لو فيه حقل ناقص رسالة الخطأ بتظهر فوق الزرار والطلب مش بيتسجّل. «إلغاء» جنبه بيقفل النموذج من غير حفظ.',
                       'It saves the request and sends it to the first-step approver; the form closes and the request shows in the table as "Awaiting approval".\n'
                       'If a field is missing, the error shows above the button and nothing is saved. "Cancel" next to it closes the form without saving.')},
            {'target': 'hr-requests-table', 'text': T('طلباتك وحالتها.',
                                              'Your requests and their status.'),
             'more': T('كل طلب بحالته: بانتظار الموافقة، موافق عليه، مرفوض، مدفوع/تمت التسوية، ملغى.\n'
                       '• 🖨️ بتطبع الطلب ورقياً.\n'
                       '• «إلغاء» بيظهر بس طول ما الطلب مسودة أو بانتظار الموافقة — بعد القرار مش هينفع.',
                       'Each request with its status: awaiting approval, approved, rejected, paid/settled, cancelled.\n'
                       '• 🖨️ prints the request on paper.\n'
                       '• "Cancel" only shows while the request is a draft or awaiting approval — not after a decision.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'hr.approvals',
        'routes': ['/approvals'],
        'title': T('صندوق الموافقات', 'Approvals inbox'),
        'summary': T('كل الطلبات التي تنتظر قرارك من كل مسارات الموافقة (طلبات الموظفين، عزل الدفعات، وغيرها)، وسجل القرارات.', 'Every request waiting for your decision across all approval flows (employee requests, batch quarantine and more), and the decision history.'),
        'audience': T('المعتمدون: المدير، المشرف، الصيادلة المسؤولون، الجودة، المشتريات.', 'Approvers: admins, supervisors, responsible pharmacists, quality, purchasing.'),
        'tabs': [
            {'key': 'pending', 'title': T('بانتظار القرار', 'Waiting for decision'), 'body': T('افتح الطلب ← «اتخاذ قرار» ← موافقة أو رفض مع ملاحظة.', 'Open the request → "Decide" → approve or reject with a note.')},
            {'key': 'history', 'title': T('السجل', 'History'), 'body': T('القرارات السابقة.', 'Past decisions.')},
        ],
        'tips': [T('السيرفر يتحقق أنك المعتمد المختص بهذه الخطوة؛ ظهور الطلب لا يعني دائماً أنك صاحب القرار.', 'The server checks that you are the right approver for this step; seeing a request does not always mean the decision is yours.')],
        'related': ['hr.mobile_approvals', 'pricing.approvals'],
        'tour': [
            {'target': 'hr-approvals-header', 'text': T('صندوق الطلبات اللي مستنية قرارك.',
                                              'The requests waiting for your decision.'),
             'more': T('صندوق واحد لكل مسارات الموافقة: طلبات الموظفين، عزل الدفعات، وغيرها.\n'
                       'لما طلب يوصل لخطوتك بيجيلك إشعار، وتقرر من هنا أو من الموبايل.',
                       'One inbox for every approval flow: employee requests, batch quarantine and more.\n'
                       'When a request reaches your step you are notified, and you decide here or on the phone.')},
            {'target': 'hr-approvals-tabs', 'text': T('«بانتظار القرار» أو «السجل».',
                                              '"Awaiting decision" or "History".'),
             'more': T('• «بانتظار القرار»: الطلبات اللي الخطوة الحالية فيها عندك (حتى لو متعددة الخطوات).\n'
                       '• «السجل»: الطلبات المقفولة — معتمد، مرفوض، ملغى، منتهي الصلاحية — للعرض بس.',
                       '• "Awaiting decision": requests whose current step is yours (even multi-step ones).\n'
                       '• "History": closed requests — approved, rejected, cancelled, expired — view only.')},
            {'target': 'hr-approvals-table', 'text': T('الطلبات: العنوان والنوع ومقدّم الطلب والحالة.',
                                              'The requests: title, type, requester and status.'),
             'more': T('لكل طلب: العنوان، النوع (اسم مسار الموافقة)، مقدّم الطلب، الحالة والتاريخ.\n'
                       'الجدول بيظهر لما يكون فيه طلبات؛ لو فاضي هتلاقي «لا توجد طلبات بانتظار القرار».',
                       'For each request: title, type (approval flow name), requester, status and date.\n'
                       'The table shows when there are requests; if empty you see "No requests awaiting decision".')},
            {'target': 'hr-approvals-decide', 'text': T('«اتخاذ قرار» للموافقة أو الرفض مع ملاحظة.',
                                              '"Decide" to approve or reject with a note.'),
             'more': T('بيفتح نافذة: «✅ موافقة» أو «❌ رفض» + ملاحظة اختيارية، وبعدين «تأكيد القرار».\n'
                       '• الموافقة بتنقل الطلب للخطوة التالية أو تقفله «موافق عليه»، والرفض بيقفله.\n'
                       '• مقدّم الطلب بيوصله إشعار بالنتيجة، والقرار متسجّل باسمك.',
                       'It opens a window: "✅ Approve" or "❌ Reject" + an optional note, then "Confirm decision".\n'
                       '• Approval moves the request to the next step or closes it as "Approved"; rejection closes it.\n'
                       '• The requester is notified of the result, and the decision is recorded under your name.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'hr.mobile_approvals',
        'routes': ['/m/approvals'],
        'title': T('الموافقات (موبايل)', 'Approvals (mobile)'),
        'summary': T('قرار سريع من الموبايل بتبديل بين «تشغيلية» (موافقات تشغيلية + طلبات تغيير السعر/الخصم) و«HR» (إجازات، إضافي، سلف، مصروفات). الطلب المتأخر عليه علامة.',
                     'Quick decisions on the phone with a toggle between "Operational" (operational approvals + price/discount change requests) and "HR" (leave, overtime, advances, expenses). Late requests are flagged.'),
        'audience': T('المدير والمشرف والمشتريات.', 'Admins, supervisors and purchasing.'),
        'tabs': [
            {'key': 'operational', 'title': T('تشغيلية', 'Operational'), 'body': T('الموافقات التشغيلية وطلبات تغيير الأسعار.', 'Operational approvals and price change requests.')},
            {'key': 'hr', 'title': T('HR', 'HR'), 'body': T('طلبات الموارد البشرية.', 'HR requests.')},
        ],
        'related': ['hr.approvals'],
        'tour': [
            {'target': 'hr-mobile-approvals-tabs', 'text': T('بدّل بين «تشغيلية» (تشمل تغيير السعر/الخصم) و«HR».',
                                              'Switch between "Operational" (including price/discount changes) and "HR".'),
             'more': T('• «تشغيلية»: الموافقات التشغيلية + طلبات تغيير سعر أو خصم صنف.\n'
                       '• «HR»: إجازات، أذونات، إضافي، سلف، مصروفات.\n'
                       'القسمين منفصلين عشان تخلّص كل نوع لوحده بسرعة.',
                       '• "Operational": operational approvals + item price or discount change requests.\n'
                       '• "HR": leave, permits, overtime, advances, expenses.\n'
                       'The two are separate so you can clear each kind quickly.')},
            {'target': 'hr-mobile-approvals-header', 'text': T('عدد الطلبات اللي بانتظار قرارك في القسم الحالي.',
                                              'How many requests await your decision in this section.'),
             'more': T('العنوان بيقولك إنت في أنهي قسم، والرقم جنبه «بانتظارك» هو عدد الطلبات اللي مستنية قرارك فيه.\n'
                       'لو صفر هتلاقي «لا توجد موافقات بانتظارك».',
                       'The title tells you which section you are in, and the number "awaiting you" next to it is how many requests need your decision.\n'
                       'If zero you see "No approvals awaiting you".')},
            {'target': 'hr-mobile-approvals-list', 'text': T('الطلبات من الأحدث، بمقدّم الطلب والتفاصيل والخطوة الحالية؛ تظهر عند وجود طلبات.',
                                              'Requests newest first, with requester, details and current step; shown when requests exist.'),
             'more': T('كل كارت: عنوان الطلب وتفاصيله، «الخطوة» الحالية، مقدّم الطلب وإمتى اتقدّم.\n'
                       'في طلبات تغيير السعر بتشوف القيمة القديمة ← الجديدة و«السبب»، فتقرر من غير ما تفتح شاشة تانية.',
                       'Each card: request title and details, current "Step", the requester and when it was submitted.\n'
                       'For price changes you see the old → new value and the "Reason", so you can decide without opening another screen.')},
            {'target': 'hr-mobile-approvals-tag', 'text': T('نوع الطلب، وعلامة «متأخر» لو تأخر عن موعده.',
                                              'The request type, and a "Late" mark if it is overdue.'),
             'more': T('الشارة الزرقا بتقول مسار الموافقة، والبنفسجي «تغيير سعر/خصم».\n'
                       '«متأخر» بالأحمر معناها إن الطلب عدّى المهلة المحددة لقراره — اديله أولوية.',
                       'The blue badge shows the approval flow; purple means "Price/discount change".\n'
                       'A red "Late" means the request passed its decision deadline — give it priority.')},
            {'target': 'hr-mobile-approvals-decide', 'text': T('«اعتماد» أو «رفض» يفتح تأكيداً مع ملاحظة؛ القرار حسب صلاحيتك ويُسجَّل.',
                                              '"Approve" or "Reject" opens a confirmation with a note; it depends on your permission and is recorded.'),
             'more': T('بتفتح نافذة من تحت فيها ملاحظة (مع الرفض: سبب الرفض مستحسن)، والقرار مش بيتنفذ غير بـ«تأكيد».\n'
                       'بعد التنفيذ الطلب بيختفي من القائمة، ولو السيرفر رفض (مش خطوتك أو مش صلاحيتك) الرسالة بتظهر في النافذة.',
                       'A sheet opens with a note (when rejecting, a reason is recommended); nothing happens until "Confirm".\n'
                       'After it runs the request leaves the list; if the server refuses (not your step or permission) the message shows in the sheet.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'hr.attendance',
        'routes': ['/m/attendance'],
        'title': T('الحضور والانصراف', 'Attendance'),
        'summary': T('تسجيل الحضور والانصراف بضغطة من الموبايل؛ يُرسل موقعك (GPS) ويتحقق السيرفر أنك داخل 200 متر من فرعك («ضمن نطاق الفرع»). بدون موقع يُسجَّل «غير مُتحقق».',
                     'Clock in and out with one tap on the phone; your GPS location is sent and the server checks you are within 200 m of your branch ("within branch range"). Without location it is recorded as "unverified".'),
        'audience': T('كل الموظفين.', 'Every employee.'),
        'tips': [T('اسمح للمتصفح بالوصول للموقع حتى يُحتسب الحضور «ضمن النطاق».', 'Allow the browser to use your location so attendance counts as "within range".')],
        'workflows': [],
        'tour': [
            {'target': 'hr-attendance-status', 'text': T('حالتك اليوم: لم تسجّل بعد، مسجّل حضور الآن، أو أنهيت يومك.',
                                              'Your status today: not checked in, checked in now, or day finished.'),
             'more': T('• 🕐 «لم تسجّل الحضور بعد»: أول ما توصل الفرع سجّل حضورك.\n'
                       '• 🟢 «أنت مسجّل حضور الآن»: يومك مفتوح لحد ما تسجّل انصراف.\n'
                       '• ✅ «أنهيت يومك»: الحضور والانصراف متسجّلين.',
                       '• 🕐 "Not checked in yet": check in as soon as you reach the branch.\n'
                       '• 🟢 "You are checked in now": your day is open until you check out.\n'
                       '• ✅ "Day finished": both check-in and check-out are recorded.')},
            {'target': 'hr-attendance-times', 'text': T('وقت الحضور والانصراف، وهل كان «ضمن نطاق الفرع» أو خارجه؛ يظهر بعد التسجيل.',
                                              'Check-in and check-out times and whether each was "within branch range"; shown after you check in.'),
             'more': T('جنب كل وقت علامة:\n'
                       '• «✓ ضمن نطاق الفرع»: كنت على بُعد 200 متر أو أقل من الفرع.\n'
                       '• «⚠ خارج النطاق» ومعاها المسافة بالمتر.\n'
                       '• «الموقع غير مُتحقق»: الموقع ما اتبعتش أو الفرع ملوش إحداثيات.',
                       'Next to each time is a mark:\n'
                       '• "✓ Within branch range": you were 200 m or less from the branch.\n'
                       '• "⚠ Out of range" with the distance in metres.\n'
                       '• "Location unverified": no location was sent, or the branch has no coordinates.')},
            {'target': 'hr-attendance-check-in', 'text': T('«📍 تسجيل الحضور» يرسل موقعك ويسجّل حضورك؛ يظهر قبل تسجيل الحضور.',
                                              '"📍 Check in" sends your location and records attendance; shown before you check in.'),
             'more': T('الضغط بيطلب موقعك من الموبايل («جارٍ تحديد الموقع...») وبعدين يسجّل وقت الحضور.\n'
                       'لو رفضت إذن الموقع الحضور بيتسجّل برضه بس «غير مُتحقق»، فاسمح بالموقع.\n'
                       'الحضور مش بيتمنع لو كنت خارج النطاق — بيتسجّل كده.',
                       'Tapping asks the phone for your location ("Locating...") then records the check-in time.\n'
                       'If you refuse location access it is still recorded but "unverified", so allow location.\n'
                       'Check-in is not blocked when out of range — it is recorded as such.')},
            {'target': 'hr-attendance-check-out', 'text': T('«🚪 تسجيل الانصراف» يظهر بعد تسجيل الحضور لإنهاء يومك.',
                                              '"🚪 Check out" appears after checking in, to end your day.'),
             'more': T('بيبعت موقعك تاني ويسجّل وقت الانصراف، وبعدها الحالة تبقى «أنهيت يومك».\n'
                       'سجّله وإنت لسه في الفرع عشان يتحسب «ضمن النطاق». مش هينفع تسجّل حضور جديد قبل ما تقفل اللي مفتوح.',
                       'It sends your location again and records the check-out time; then the status becomes "Day finished".\n'
                       'Do it while still at the branch so it counts "within range". You cannot check in again while a check-in is open.')},
            {'target': 'hr-attendance-geofence-note', 'text': T('موقعك يُقارن بموقع فرعك (ضمن 200 متر)؛ بدون موقع يُسجَّل «غير مُتحقق».',
                                              'Your location is checked against your branch (within 200 m); without it, it is recorded "unverified".'),
             'more': T('السيرفر بيحسب المسافة بين موقعك وإحداثيات فرعك المسجّلة في الإعدادات.\n'
                       'لو الفرع ملوش إحداثيات، كل التسجيلات هتطلع «غير مُتحقق» — بلّغ المدير يضيفها من «الإعدادات» ← «الفروع».',
                       'The server measures the distance between you and your branch coordinates saved in settings.\n'
                       'If the branch has no coordinates every record shows "unverified" — ask an admin to add them in "Settings" → "Branches".')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'hr.qa',
        'routes': ['/m/qa', '/m/qa/:id'],
        'title': T('مراجعات الجودة للفروع', 'Branch quality inspections'),
        'summary': T('جولة جودة في الفرع من الموبايل: «مراجعة جديدة» باختيار القالب والفرع ← لكل بند: مطابق / مخالفة (مع ملاحظة) / لا ينطبق ← «حفظ كمسودة» أو «إرسال» فتُحسب الدرجة.',
                     'A quality walk-through at the branch on the phone: "New inspection" with a template and branch → per item: compliant / violation (with a note) / not applicable → "Save draft" or "Submit" to compute the score.'),
        'audience': T('مدير الجودة والمشرفون والصيادلة.', 'The quality manager, supervisors and pharmacists.'),
        'workflows': [],
        'tour': [
            {'target': 'hr-qa-new', 'text': T('زر «+» يبدأ مراجعة جودة جديدة.',
                                              'The "+" button starts a new quality inspection.'),
             'more': T('الزرار العايم تحت بيفتح نموذج «مراجعة جديدة» فوق القائمة.\n'
                       'استخدمه أول ما تبدأ جولة جودة في الفرع، والمراجعة مش بتتعمل غير لما تضغط «ابدأ المراجعة».',
                       'The floating button opens the "New inspection" form above the list.\n'
                       'Use it when you start a quality walk-through at a branch; nothing is created until you press "Start inspection".')},
            {'target': 'hr-qa-new-form', 'text': T('اختر القالب والفرع ثم «ابدأ المراجعة»؛ يظهر بعد الضغط على «+».',
                                              'Choose the template and branch, then "Start inspection"; shown after tapping "+".'),
             'more': T('• «القالب»: قائمة البنود اللي هتراجعها.\n'
                       '• «الفرع»: حسب دورك يا إما تختار الفرع من القائمة، يا إما بيتحدد فرعك تلقائياً.\n'
                       '«ابدأ المراجعة» بينشئ مسودة ويفتح بنودها على طول.',
                       '• "Template": the list of items you will check.\n'
                       '• "Branch": depending on your role you either pick the branch from the list, or your own branch is set automatically.\n'
                       '"Start inspection" creates a draft and opens its items straight away.')},
            {'target': 'hr-qa-list', 'text': T('المراجعات الأخيرة بالفرع والقالب والمراجِع والتاريخ؛ اضغط مراجعة لفتحها.',
                                              'Recent inspections with branch, template, inspector and date; tap one to open it.'),
             'more': T('آخر المراجعات من الأحدث. اضغط على أي واحدة:\n'
                       '• لو مسودة: تكمّل تعبئة البنود.\n'
                       '• لو مُرسَلة: تشوف النتيجة والملاحظات للعرض بس.',
                       'Latest inspections, newest first. Tap any one:\n'
                       '• If a draft: continue filling the items.\n'
                       '• If submitted: see the result and notes, view only.')},
            {'target': 'hr-qa-status', 'text': T('«مسودة» أو الدرجة % بعد الإرسال.',
                                              '"Draft", or the score % once submitted.'),
             'more': T('الدرجة = البنود المطابقة ÷ (المطابقة + المخالفات)، و«لا ينطبق» مش بيتحسب.\n'
                       'اللون: أخضر 90% وأكتر، أصفر من 70%، أحمر أقل من 70%.',
                       'Score = compliant items ÷ (compliant + violations); "Not applicable" is not counted.\n'
                       'Colour: green 90% and above, amber from 70%, red below 70%.')},
            {'target': 'hr-qa-item-result', 'text': T('داخل المراجعة المفتوحة: لكل بند «مطابق» أو «مخالفة» (مع ملاحظة) أو «لا ينطبق».',
                                              'Inside an open inspection: per item "Compliant", "Violation" (with a note) or "Not applicable".'),
             'more': T('اختار نتيجة كل بند وإنت ماشي في الفرع. «مخالفة» بتفتح خانة «ملاحظة المخالفة» — اكتب فيها اللي شفته بالظبط.\n'
                       'فوق هتلاقي عدّاد «أُجيب كذا من كذا» عشان تعرف فاضلك كام بند.',
                       'Pick each item\'s result as you walk the branch. "Violation" opens a "Violation note" box — write exactly what you saw.\n'
                       'At the top an "answered X of Y" counter shows how many items are left.')},
            {'target': 'hr-qa-save', 'text': T('داخل المراجعة: «حفظ كمسودة» أو «✅ إرسال» لحساب الدرجة.',
                                              'Inside the inspection: "Save draft" or "✅ Submit" to compute the score.'),
             'more': T('• «حفظ كمسودة»: بيحفظ اللي عملته وتقدر تكمّل بعدين.\n'
                       '• «✅ إرسال»: بيحسب الدرجة ويقفل المراجعة — بعده مفيش تعديل.\n'
                       'الإرسال مش متاح غير لما تجاوب على بند واحد على الأقل.',
                       '• "Save draft": saves your work so you can continue later.\n'
                       '• "✅ Submit": computes the score and locks the inspection — no edits after that.\n'
                       'Submit is only available once at least one item is answered.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
