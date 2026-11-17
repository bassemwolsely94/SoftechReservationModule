from . import T

_JOB_OPEN = T('اضغط على سطر الأمر في الجدول ليظهر تفصيله تحته.', 'Click a job row in the grid to show its detail under it.')

MODULE = {
    'key': 'rpa', 'group': 'admin', 'icon': '🤖',
    'brief': T('روبوت يكتب إذن الصرف في شاشة SOFTECH بدلاً منك، الآن تجربة بدون حفظ.',
               'A robot that types the issue order into the SOFTECH screen for you, for now as a no-save dry run.'),
    'title': T('روبوت الإدخال', 'Entry robot'),
    'summary': T(
        'ترفع ملف Excel لإذن صرف بين فرعين، فيقرأ النظام الأسطر ويطابق الأصناف. شخص آخر غيرك يعتمد الأمر (قاعدة العينين الأربع). '
        'بعدها يعمل برنامج الروبوت على جهاز Windows مسجّل باسمك ويكتب الأسطر في شاشة SOFTECH حسب وصفة معتمدة. '
        'في المرحلة الأولى كل أمر «تجربة بدون حفظ»: يكتب الروبوت ثم يلغي، ولا يُحفظ شيء في SOFTECH. '
        'أي مستند يتعثر يظهر «يحتاج مراجعة» ويحسمه شخص بسبب مكتوب. الروبوت لا يكتب إلا عبر الوصفة المعتمدة، وكل خطوة تُسجَّل.',
        'You upload an Excel issue order between two branches and the system reads the lines and matches the items. Someone '
        'other than you approves the job (the four-eyes rule). Then the robot program on a Windows device registered in your name '
        'types the lines into the SOFTECH screen under an approved recipe. In Stage 1 every job is a "no-save dry run": the robot '
        'types and then cancels, so nothing is saved in SOFTECH. A document that stalls shows "needs review" and a person settles '
        'it with a written reason. The robot writes only through the approved recipe, and every step is logged.'),
    'journeys': [
        {'key': 'upload_and_approve', 'shell': 'desktop', 'roles': ['admin', 'supervisor', 'purchasing', 'quality_manager'],
         'title': T('من الملف إلى التجربة', 'From the file to the dry run'),
         'summary': T('رفع إذن صرف، اعتماده من شخص آخر، ومتابعة المستند.',
                      'Upload an issue order, have someone else approve it, and follow the document.'),
         'steps': [
            {'screen': 'rpa.main', 'target': 'rpa-main-upload', 'perm': 'rpa',
             'label': T('رفع ملف', 'Upload file'),
             'text': T('اختر الفرع المصدر والفرع المستلم وملف Excel، ثم «رفع الملف».',
                       'Pick the source and receiving branch and the Excel file, then "Upload file".')},
            {'screen': 'rpa.main', 'target': 'rpa-main-jobs', 'perm': 'rpa',
             'label': T('الأوامر', 'Jobs'),
             'text': T('الأمر الجديد «بانتظار الاعتماد» وعليه «تجربة بدون حفظ».',
                       'The new job is "awaiting approval" and carries "no-save dry run".'),
             'open_hint': _JOB_OPEN},
            {'screen': 'rpa.main', 'target': 'rpa-main-job-approve', 'perm': 'rpa',
             'label': T('اعتماد الأمر', 'Approve job'),
             'text': T('شخص غير الرافع يفتح الأمر ويعتمده؛ الرافع نفسه يرفضه الخادم.',
                       'Someone other than the uploader opens the job and approves it; the server refuses the uploader.'),
             'warn': T('اعتمد بعد مراجعة الأسطر غير المطابقة والتحذيرات.',
                       'Approve only after reviewing unmatched lines and warnings.'),
             'open_hint': _JOB_OPEN},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في روبوت الإدخال', 'A tour of the entry robot'),
            'summary': T('من رفع الملف إلى المستند والأجهزة.', 'From the upload to the document and the devices.'),
            'roles': ['admin', 'supervisor', 'purchasing', 'quality_manager'],
            'steps': [
                {'target': 'nav-rpa', 'nav': '/rpa',
                 'text': T('«الإدارة» ← «روبوت الإدخال».', '"Administration" → "Entry robot".'),
                 'more': T('الشاشة دي بترفع إذن الصرف وتتابع الروبوت وهو بيكتب في SOFTECH.\n'
                           '• المرحلة الأولى تجربة بدون حفظ: مفيش حاجة بتتحفظ في SOFTECH.',
                           'This screen uploads the issue order and follows the robot typing into SOFTECH.\n'
                           '• Stage 1 is a no-save dry run: nothing is saved in SOFTECH.')},
                {'target': 'rpa-main-status', 'route': '/rpa',
                 'text': T('الشريط يوضح هل الروبوت شغّال أم متوقف من الإعدادات.', 'The strip shows whether the robot is on or switched off in settings.'),
                 'more': T('لو كتب «الروبوت متوقف من الإعدادات» فلن يستلم أي جهاز مستندات حتى يفعّله المدير.\n'
                           '• تجد هنا أيضًا شارة «تجربة بدون حفظ» وعدد أجهزتك المتصلة.',
                           'If it says "the robot is off in settings" no device will take documents until the admin turns it on.\n'
                           '• You also see the "no-save dry run" badge and how many of your devices are online.')},
                {'target': 'rpa-main-tabs', 'route': '/rpa',
                 'text': T('أربع تبويبات: الأوامر، رفع ملف، أجهزتي، والوصفات للمدير.', 'Four tabs: jobs, upload, my devices, and recipes for the admin.'),
                 'more': T('ابدأ من «رفع ملف» ثم تابع الأمر في «الأوامر».\n'
                           '• «أجهزتي» لتسجيل جهاز Windows الذي يشغّل الروبوت.',
                           'Start from "Upload file", then follow the job in "Jobs".\n'
                           '• "My devices" registers the Windows device that runs the robot.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'rpa.main',
        'routes': ['/rpa'],
        'title': T('روبوت الإدخال', 'Entry robot'),
        'summary': T('رفع إذن الصرف ومتابعة الأوامر والمستندات والأجهزة وتجربة الروبوت بدون حفظ.',
                     'Upload the issue order and follow the jobs, documents, devices and the no-save robot dry run.'),
        'audience': T('من لديه صلاحية «روبوت الإدخال»: عرض / إنشاء / تعديل / اعتماد. الوصفات للمدير فقط. الخادم يفرض كل صلاحية.',
                      'Anyone with the "Entry robot" permission: view / create / edit / approve. Recipes are admin only. The server enforces every right.'),
        'tabs': [
            {'key': 'jobs', 'title': T('الأوامر', 'Jobs'),
             'body': T('كل أمر رفعته أو ترى فرعه، من الأحدث. العمود «الحالة»: بانتظار الاعتماد، معتمد، ملغي، تم. '
                       'شارة «تجربة بدون حفظ» على كل أمر في المرحلة الأولى. افتح أمرًا (Enter أو الضغط) لترى مستنداته، '
                       'ثم افتح مستندًا لترى أسطره بحالة المطابقة والرسالة والتحذير، والتشغيلات بخطواتها ولقطات الشاشة. '
                       'قاعدة العينين: الذي رفع الأمر لا يعتمده، شخص آخر يضغط «اعتماد الأمر». «إلغاء الأمر» قبل التشغيل. '
                       'مستند «يحتاج مراجعة» يعني أن الروبوت توقف أو لم يتأكد؛ اكتب سبب الحسم في الخانة التي تظهر تحت العنوان واضغط «سجّل الحسم». '
                       'الجدول يترتب بالضغط على عنوان العمود، والأسهم تنقلك بين الأوامر.',
                       'Every job you uploaded or whose branch you may see, newest first. "Status": awaiting approval, approved, cancelled, done. '
                       'A "no-save dry run" badge sits on every Stage 1 job. Open a job (Enter or a click) to see its documents, then open a document '
                       'to see its lines with match status, message and warning, and the runs with their steps and screenshots. '
                       'Four-eyes rule: whoever uploaded a job does not approve it; someone else presses "Approve job". "Cancel job" works before a run. '
                       'A "needs review" document means the robot stopped or could not be sure; write the reason in the box that appears at the top and press '
                       '"Record resolution". The grid sorts by clicking a column header, and the arrows move between jobs.')},
            {'key': 'upload', 'title': T('رفع ملف', 'Upload file'),
             'body': T('ارفع ملف Excel لإذن صرف من فرع إلى فرع. الشاشة الوحيدة المتاحة الآن «إذن صرف للفروع». اختر «من فرع» و«إلى فرع» (المستلم) '
                       'وكود المخزن إن لزم. الخادم يقرأ الملف ويطابق الأصناف ويرفض: فرعًا خارج فروعك، أو فرعًا مغلقًا، أو الفرع المستلم نفسه المصدر، '
                       'أو ملفًا سبق رفعه. بعد الرفع يصبح الأمر «بانتظار الاعتماد» ويحتاج شخصًا آخر.',
                       'Upload an Excel issue order from one branch to another. The only screen available now is "Branch issue order". Pick "From branch" and '
                       '"To branch" (the receiver) and the store code if needed. The server reads the file, matches the items and refuses: a branch outside yours, '
                       'a closed branch, the receiving branch equal to the source, or a file uploaded before. After the upload the job is "awaiting approval" and '
                       'needs another person.')},
            {'key': 'devices', 'title': T('أجهزتي', 'My devices'),
             'body': T('الأجهزة التي يعمل عليها برنامج الروبوت باسمك. اكتب اسم الجهاز واضغط «إضافة هذا الجهاز»: يظهر رمز التشغيل مرة واحدة مع زر نسخ '
                       'وعبارة «انسخه الآن، لن يظهر مرة أخرى». الخادم يحفظ بصمة الرمز فقط فلا يمكن عرضه ثانيةً؛ لو ضاع ألغِ الجهاز وأضف غيره. '
                       'الجهاز «متصل» لو ظهر خلال آخر دقيقتين. «إلغاء الجهاز» يوقفه فورًا. المدير يرى كل الأجهزة.',
                       'The devices the robot program runs on in your name. Type a device name and press "Add this device": the run token shows once with a copy '
                       'button and the line "Copy it now, it will not show again". The server keeps only a fingerprint of the token so it cannot be shown again; '
                       'if lost, revoke the device and add another. A device is "online" if seen in the last two minutes. "Revoke device" stops it at once. '
                       'The admin sees all devices.')},
            {'key': 'recipes', 'title': T('الوصفات', 'Recipes'),
             'body': T('للمدير فقط. الوصفة هي تسجيل ضغطات شاشة SOFTECH (ملف .dld) مع خريطة الحقول. ارفعها «كمسودة»، ثم يعتمدها مدير آخر '
                       '(العينان الأربع أيضًا): الوصفة المعتمدة تتجمد ولا تتغير، وتكون واحدة معتمدة فقط لكل شاشة. '
                       'الأمر المعتمد يحمل الوصفة المعتمدة وقت اعتماده.',
                       'Admin only. A recipe is a recording of the SOFTECH screen keystrokes (a .dld file) with its field map. Upload it "as a draft", then '
                       'another admin approves it (four-eyes again): an approved recipe is frozen and unchangeable, and only one is approved per screen. '
                       'An approved job carries the approved recipe from the moment it was approved.')},
        ],
        'steps': [
            T('ارفع الملف من «رفع ملف»، ثم افتح الأمر من «الأوامر» وراجع الأسطر غير المطابقة والتحذيرات.',
              'Upload the file from "Upload file", then open the job in "Jobs" and review unmatched lines and warnings.'),
            T('اطلب من زميل غيرك أن يعتمد الأمر. الروبوت لا يبدأ قبل الاعتماد.',
              'Ask a colleague other than you to approve the job. The robot does not start before approval.'),
            T('أثناء التشغيل «ارفع يدك عن الكيبورد»: الروبوت يكتب في SOFTECH، وأي لمسة قد تُدخل بياناتك في الخانة الخطأ.',
              'While it runs, "take your hands off the keyboard": the robot types into SOFTECH and any touch may put your input in the wrong field.'),
            T('مستند «يحتاج مراجعة»: افتحه وافحص SOFTECH، ثم اكتب سبب الحسم واضغط «سجّل الحسم».',
              'A "needs review" document: open it, check SOFTECH, then write the resolution reason and press "Record resolution".'),
        ],
        'tips': [
            T('كل الأوامر الآن «تجربة بدون حفظ»: يكتب الروبوت ثم يلغي، ولا يُحفظ أي مستند في SOFTECH. التشغيل الحقيقي يُفتح في مرحلة لاحقة بموافقة المالك.',
              'Every job is now a "no-save dry run": the robot types and then cancels, and no document is saved in SOFTECH. Live running opens in a later stage with the owner\'s approval.'),
            T('لو كتب الشريط «الروبوت متوقف من الإعدادات» فلن يستلم أي جهاز مستندات. المفتاح عند المدير.',
              'If the strip says "the robot is off in settings", no device takes documents. The switch is with the admin.'),
            T('«يحتاج مراجعة» لا يعني أن شيئًا حُفظ بالخطأ بالضرورة، بل أن الروبوت لم يستطع التأكد. تحقق من SOFTECH قبل أن تحسم.',
              '"Needs review" does not necessarily mean something was saved wrongly; it means the robot could not be sure. Check SOFTECH before you resolve.'),
            T('الرمز يظهر مرة واحدة فقط. من يملكه يشغّل الروبوت باسمك، فلا ترسله في رسالة.',
              'The token shows only once. Whoever holds it can run the robot in your name, so do not send it in a message.'),
            T('كل جدول يترتب بالضغط على عنوان العمود. أسماء الفروع تظهر بالكود والاسم.',
              'Every grid sorts by clicking a column header. Branches show as code and name.'),
        ],
        'faq': [
            {'q': T('لماذا لا أستطيع اعتماد أمر رفعته أنا؟', 'Why can I not approve a job I uploaded?'),
             'a': T('قاعدة العينين الأربع: الرافع والمعتمد شخصان مختلفان، والخادم يرفض اعتماد الرافع نفسه.',
                    'The four-eyes rule: the uploader and the approver are two different people, and the server refuses the uploader.')},
            {'q': T('ظهر «تم رفع هذا الملف من قبل»، ماذا أفعل؟', 'It says "this file was uploaded before", what now?'),
             'a': T('افتح الأمر المذكور في الرسالة من «الأوامر». لو ألغيته يمكنك رفع الملف من جديد.',
                    'Open the job named in the message from "Jobs". If you cancel it you can upload the file again.')},
        ],
        'related': ['admin.sync'],
        'tour': [
            {'target': 'rpa-main-status', 'label': T('حالة الروبوت', 'Robot status'),
             'text': T('هل الروبوت شغّال أم «متوقف من الإعدادات»، وشارة «تجربة بدون حفظ»، وأجهزتك المتصلة.',
                       'Whether the robot is on or "off in settings", the "no-save dry run" badge, and your online devices.')},
            {'target': 'rpa-main-tabs', 'label': T('الأوامر · رفع ملف · أجهزتي', 'Jobs · Upload · Devices'),
             'text': T('أربع تبويبات؛ «الوصفات» تظهر للمدير فقط.', 'Four tabs; "Recipes" shows to the admin only.')},
            {'target': 'rpa-main-jobs', 'label': T('الأوامر', 'Jobs'),
             'text': T('أمر في كل سطر. Enter أو الضغط يفتح مستنداته؛ الأسهم للتنقل.',
                       'One job per row. Enter or a click opens its documents; arrows move.'),
             'open_hint': T('افتح تبويب «الأوامر».', 'Open the "Jobs" tab.')},
            {'target': 'rpa-main-job-approve', 'label': T('اعتماد الأمر', 'Approve job'),
             'text': T('شخص غير الرافع يعتمد الأمر قبل أن يستلمه أي جهاز.',
                       'Someone other than the uploader approves the job before any device takes it.'),
             'warn': T('الرافع لا يعتمد أمره، والخادم يرفض. راجع الأسطر أولًا.',
                       'The uploader does not approve their own job, and the server refuses. Review the lines first.'),
             'open_hint': _JOB_OPEN},
            {'target': 'rpa-main-resolve', 'label': T('يحتاج مراجعة', 'Needs review'),
             'text': T('اكتب سبب الحسم هنا بعد فحص SOFTECH، ثم «سجّل الحسم». السبب مطلوب.',
                       'Write the resolution reason here after checking SOFTECH, then "Record resolution". The reason is required.'),
             'open_hint': T('يظهر فقط في مستند حالته «يحتاج مراجعة».', 'Shows only in a document whose status is "needs review".')},
            {'target': 'rpa-main-upload', 'label': T('رفع ملف', 'Upload file'),
             'text': T('فرع المصدر والمستلم وملف Excel. الخادم يرفض المغلق والمكرر.',
                       'Source and receiving branch and the Excel file. The server refuses closed branches and duplicates.'),
             'open_hint': T('افتح تبويب «رفع ملف».', 'Open the "Upload file" tab.')},
            {'target': 'rpa-main-devices', 'label': T('إضافة هذا الجهاز', 'Add this device'),
             'text': T('يظهر رمز الجهاز مرة واحدة: «انسخه الآن، لن يظهر مرة أخرى».',
                       'The device token shows once: "Copy it now, it will not show again".'),
             'open_hint': T('افتح تبويب «أجهزتي».', 'Open the "My devices" tab.')},
            {'target': 'rpa-main-recipes', 'label': T('الوصفات', 'Recipes'),
             'text': T('للمدير: تسجيلات الشاشة. تُرفع كمسودة ويعتمدها مدير آخر ثم تتجمد.',
                       'Admin: the screen recordings. Uploaded as a draft, approved by another admin, then frozen.'),
             'open_hint': T('افتح تبويب «الوصفات» (للمدير).', 'Open the "Recipes" tab (admin).')},
        ],
        'updated': '2026-11-16',
    },
]
