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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
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
        'updated': '2026-10-10',
    },
    {
        'key': 'hr.qa',
        'routes': ['/m/qa', '/m/qa/:id'],
        'title': T('مراجعات الجودة للفروع', 'Branch quality inspections'),
        'summary': T('جولة جودة في الفرع من الموبايل: «مراجعة جديدة» باختيار القالب والفرع ← لكل بند: مطابق / مخالفة (مع ملاحظة) / لا ينطبق ← «حفظ كمسودة» أو «إرسال» فتُحسب الدرجة.',
                     'A quality walk-through at the branch on the phone: "New inspection" with a template and branch → per item: compliant / violation (with a note) / not applicable → "Save draft" or "Submit" to compute the score.'),
        'audience': T('مدير الجودة والمشرفون والصيادلة.', 'The quality manager, supervisors and pharmacists.'),
        'workflows': [],
        'updated': '2026-10-10',
    },
]
