from . import T

# Longer explanations ("more") shared by the screen tour and the module tour.
INV_MORE_NEW = T(
    'استخدمه لما توصلك فاتورة شراء ورقية أو PDF من مورد بدل ما تكتبها بإيدك في SOFTECH.\n'
    '• بيفتح نافذة «فاتورة مورد جديدة»: الفرع (إجباري)، اسم المورد، رقم الفاتورة، التاريخ، وصورة أو PDF الفاتورة.\n'
    '• بعد الحفظ الفاتورة بتتفتح على طول، والنظام بيقرأ الصورة (OCR) ويطابق كل سطر بصنف من الكتالوج.\n'
    '• لسه مفيش أي حاجة اتكتبت في SOFTECH في الخطوة دي.',
    'Use it when a paper or PDF purchase invoice arrives from a supplier, instead of typing it into SOFTECH by hand.\n'
    '• It opens the "New supplier invoice" window: branch (required), supplier name, invoice number, date, and the invoice image or PDF.\n'
    '• After saving, the invoice opens straight away and the system reads the image (OCR) and matches each line to a catalog item.\n'
    '• Nothing is written to SOFTECH at this step.')
INV_MORE_FILTERS = T(
    'اختار فرع و/أو حالة عشان تركّز على شغلك.\n'
    '• «قيد المراجعة»: فواتير محتاجة حد يراجع سطورها.\n'
    '• «مُأكَّدة» و«فشل الترحيل»: جاهزة للمعاينة والترحيل أو محتاجة إعادة محاولة.\n'
    '• «مُرحّلة إلى ERP»: خلصت وبقت مستند في SOFTECH.',
    'Pick a branch and/or a status to focus on your work.\n'
    '• "In review": invoices whose lines need checking.\n'
    '• "Confirmed" and "Posting failed": ready for the preview and posting, or need a retry.\n'
    '• "Posted to ERP": done and now a SOFTECH document.')
INV_MORE_LIST = T(
    'كل كارت فاتورة فيه المورد والحالة ونسبة السطور المؤكدة من إجمالي السطور.\n'
    '• اضغط الكارت عشان تفتح الفاتورة في نفس الصفحة وتراجعها.\n'
    '• النسبة الواطية معناها لسه فيه سطور الصنف بتاعها محتاج تأكيد.',
    'Each invoice card shows the supplier, the status and how many lines are confirmed out of all lines.\n'
    '• Click a card to open the invoice on the same page and review it.\n'
    '• A low percentage means some lines still need their item confirmed.')
INV_MORE_ACTIONS = T(
    'الأزرار هنا بتظهر حسب حالة الفاتورة:\n'
    '• «⚠ فحص الانحرافات» يطلع تقرير بالسطور المشكوك فيها (سعر بعيد عن الكتالوج، خصم عالي، صنف مكرر…)، و«🔄 إعادة OCR» لو القراءة وحشة.\n'
    '• «✓ تأكيد الفاتورة» بيغيّر الحالة لـ «مُأكَّدة» بس — مش بيكتب في SOFTECH.\n'
    '• «🛡 فحص التحقق» ثم «⇪ ترحيل إلى ERP» بيفتح معاينة: الأخطاء بتمنع الترحيل والتحذيرات محتاجة «راجعت التحذيرات وأريد المتابعة». الترحيل للمدير والمشتريات والمشرف، ولو الفاتورة اترحّلت قبل كده مش بتتكتب تاني.',
    'The buttons here depend on the invoice status:\n'
    '• "⚠ Check deviations" lists suspicious lines (price far from the catalog, high discount, duplicated item…), and "🔄 Re-run OCR" helps when the reading is poor.\n'
    '• "✓ Confirm invoice" only changes the status to "Confirmed" — it does not write to SOFTECH.\n'
    '• "🛡 Validation check" then "⇪ Post to ERP" opens a preview: errors block posting and warnings need "I reviewed the warnings". Posting is for admin, purchasing and supervisors, and an invoice already posted is never written twice.')
INV_MORE_HEADER = T(
    'دي بيانات رأس الفاتورة زي ما اتقرت: المورد، رقم وتاريخ الفاتورة، الخصم العام (نسبة أو مبلغ) والإجمالي.\n'
    '• قارنها بالورقة الأصلية قبل التأكيد.\n'
    '• «تعديل» بيظهر بس طول ما الفاتورة لسه قابلة للتعديل (قبل التأكيد).',
    'This is the invoice header as it was read: supplier, invoice number and date, global discount (percent or amount) and total.\n'
    '• Compare it with the paper original before confirming.\n'
    '• "Edit" shows only while the invoice can still be edited (before confirming).')
INV_MORE_LINES = T(
    'كل سطر: الصنف اللي النظام طابقه، الكمية، سعر الوحدة والخصم، ودرجة ثقة القراءة.\n'
    '• السطور منخفضة الثقة أو اللي الاسم العربي والعلمي فيها أشاروا لصنفين مختلفين محتاجة انتباهك.\n'
    '• بالكيبورد: ↑↓ للتنقل، Enter يأكّد الصنف المقترح وينقلك للسطر اللي بعده، M يعرض اقتراحات المطابقة.',
    'Each line: the item the system matched, quantity, unit price and discount, and the reading confidence.\n'
    '• Lines with low confidence, or where the Arabic and scientific names point to different items, need your attention.\n'
    '• Keyboard: ↑↓ to move, Enter confirms the suggested item and moves to the next line, M shows match suggestions.')

MODULE = {
    'key': 'invoices', 'group': 'purchasing', 'icon': '🧾',
    'brief': T('فاتورة المورد بالصورة: النظام يقراها، تراجعها، وبعدين تترحّل لـ SOFTECH.',
               'A supplier invoice from a photo: the system reads it, you review it, then it is posted to SOFTECH.'),
    'title': T('فواتير الموردين', 'Supplier invoices'),
    'summary': T(
        'إدخال فواتير الشراء من الموردين (ومرتجعاتها) بدل كتابتها يدوياً في SOFTECH: ارفع صورة/PDF الفاتورة ← النظام يقرأها (OCR) ويطابق كل سطر بصنف من الكتالوج ← '
        'تراجع السطور منخفضة الثقة وتؤكد الفاتورة ← معاينة الترحيل تتحقق من قواعد الحفظ في SOFTECH (أخطاء تمنع، تحذيرات تحتاج تأكيداً) ← الترحيل إلى SOFTECH '
        '(عند تفعيله) ثم التحقق أن المستند موجود فعلاً.',
        'Enter supplier purchase invoices (and returns) instead of typing them into SOFTECH: upload the invoice photo/PDF → the system reads it (OCR) and matches each line to a catalog item → '
        'review low-confidence lines and confirm the invoice → the posting preview checks SOFTECH saving rules (errors block, warnings need confirmation) → post to SOFTECH '
        '(when enabled) then verify the document really exists.'),
    'workflows': [{
        'title': T('مراحل الفاتورة', 'Invoice stages'),
        'model': 'invoices.SupplierInvoice', 'field': 'status',
        'states': [
            {'key': 'pending', 'label': T('في الانتظار', 'Pending'), 'desc': T('رُفعت ولم تُقرأ بعد.', 'Uploaded, not read yet.'), 'next': ['processing']},
            {'key': 'processing', 'label': T('جاري المعالجة', 'Processing'), 'desc': T('القراءة الآلية (OCR) والمطابقة جارية.', 'Automatic reading (OCR) and matching in progress.'), 'next': ['review']},
            {'key': 'review', 'label': T('قيد المراجعة', 'In review'), 'desc': T('راجع السطور والمطابقات والأسعار والخصومات.', 'Review lines, matches, prices and discounts.'), 'next': ['confirmed', 'rejected']},
            {'key': 'confirmed', 'label': T('مُأكَّدة', 'Confirmed'), 'desc': T('البيانات صحيحة وجاهزة لمعاينة الترحيل.', 'Data correct and ready for the posting preview.'), 'next': ['queued', 'pushing']},
            {'key': 'rejected', 'label': T('مرفوضة', 'Rejected'), 'desc': T('فاتورة خاطئة أو مكررة.', 'Wrong or duplicate invoice.')},
            {'key': 'queued', 'label': T('بانتظار الترحيل', 'Queued for posting'), 'desc': T('تنتظر الترحيل لـ SOFTECH.', 'Waiting to be posted to SOFTECH.'), 'next': ['pushing']},
            {'key': 'pushing', 'label': T('جارٍ الترحيل', 'Posting'), 'desc': T('تُكتب الآن في SOFTECH.', 'Being written to SOFTECH.'), 'next': ['finalized', 'push_failed']},
            {'key': 'finalized', 'label': T('مُرحَّلة إلى ERP', 'Posted to ERP'), 'desc': T('أصبحت مستند شراء في SOFTECH برقم مستند. «تم التحقق» يؤكد وجوده.', 'It is now a purchase document in SOFTECH with a number. "Verified" confirms it exists.')},
            {'key': 'push_failed', 'label': T('فشل الترحيل', 'Posting failed'), 'desc': T('لم يكتمل — راجع السبب ثم أعد المحاولة.', 'Did not complete — check the reason and retry.'), 'next': ['pushing']},
        ],
    }],
    'journeys': [
        {'key': 'post', 'shell': 'desktop', 'roles': ['admin', 'purchasing'],
         'title': T('رحلة الفاتورة: من الصورة إلى SOFTECH', 'Invoice: from photo to SOFTECH'),
         'summary': T('ارفع الفاتورة، راجع السطور، أكّدها، عاين الترحيل، رحّل، ثم تحقق من المستند.',
                      'Upload the invoice, review lines, confirm, preview posting, post, then verify the document.'),
         'steps': [
            {'screen': 'invoices.main', 'target': 'invoices-main-new', 'perm': 'invoices',
             'label': T('+ فاتورة جديدة', '+ New invoice'),
             'text': T('ابدأ من هنا بفاتورة المورد الورقية.', 'Start here with the paper supplier invoice.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-new-upload', 'perm': 'invoices',
             'label': T('صورة الفاتورة (OCR)', 'Invoice image (OCR)'),
             'text': T('اختر الفرع والمورد، وارفع صورة أو PDF واضح.', 'Pick the branch and supplier, and upload a clear photo or PDF.'),
             'open_hint': T('اضغط «+ فاتورة جديدة».', 'Press "+ New invoice".')},
            {'screen': 'invoices.main', 'target': 'invoices-main-new-create', 'perm': 'invoices',
             'label': T('إنشاء الفاتورة', 'Create invoice'),
             'text': T('ينشئ الفاتورة ويبدأ القراءة الآلية. لا شيء يُكتب في SOFTECH.', 'Creates the invoice and starts automatic reading. Nothing is written to SOFTECH.'),
             'open_hint': T('داخل نموذج الفاتورة الجديدة.', 'Inside the new-invoice form.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-confirm-ready', 'perm': 'invoices',
             'label': T('✓ تأكيد الجاهزة', '✓ Confirm ready lines'),
             'text': T('أكّد السطور الواضحة مرة واحدة، وراجع الباقي سطراً سطراً.', 'Confirm the clear lines in one go, then review the rest line by line.'),
             'open_hint': T('افتح الفاتورة بعد انتهاء القراءة.', 'Open the invoice after the reading finishes.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-view', 'perm': 'invoices',
             'label': T('⊞ جدول SofTech', '⊞ SofTech grid'),
             'text': T('قارن الإجمالي النهائي بإجمالي الفاتورة الورقية.', 'Compare the final total with the paper invoice total.'),
             'open_hint': T('افتح أي فاتورة فيها سطور.', 'Open any invoice that has lines.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-confirm', 'perm': 'invoices',
             'label': T('✓ تأكيد الفاتورة', '✓ Confirm invoice'),
             'text': T('البيانات صحيحة؟ أكّد. السطور تُقفل بعدها.', 'Data correct? Confirm. The lines lock after this.'),
             'warn': T('بعد التأكيد لا تعديل على السطور.', 'No line edits after confirming.'),
             'open_hint': T('افتح فاتورة «قيد المراجعة».', 'Open an "In review" invoice.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-dupcheck', 'perm': 'invoices',
             'label': T('🔎 فحص التكرار', '🔎 Duplicate check'),
             'text': T('يبحث في SOFTECH عن مستند لنفس المورد بنفس الرقم أو الإجمالي أو الأصناف. قراءة فقط.',
                       'Searches SOFTECH for a document from the same supplier with the same number, total or items. Read only.'),
             'open_hint': T('افتح أي فاتورة غير مُرحَّلة.', 'Open any invoice not posted yet.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-push', 'perm': 'invoices',
             'label': T('⇪ ترحيل إلى ERP', '⇪ Post to ERP'),
             'text': T('افتح المعاينة: صحّح الأخطاء وراجع التحذيرات.', 'Open the preview: fix errors and review warnings.'),
             'warn': T('الأخطاء تمنع الترحيل — لا تحاول الالتفاف عليها.', 'Errors block posting — do not try to work around them.'),
             'open_hint': T('افتح فاتورة «مُأكَّدة».', 'Open a "Confirmed" invoice.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-push-confirm', 'perm': 'invoices',
             'label': T('⇪ تأكيد الترحيل', '⇪ Confirm posting'),
             'text': T('يكتب المستند النهائي في SOFTECH ويظهر رقمه.', 'Writes the final document into SOFTECH and shows its number.'),
             'warn': T('نهائي في SOFTECH: المخزون ورصيد المورد يتغيران. محمي ضد التكرار.',
                       'Final in SOFTECH: stock and supplier balance change. Protected against double posting.'),
             'open_hint': T('داخل نافذة المعاينة.', 'Inside the preview window.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-verify', 'perm': 'invoices',
             'label': T('🔄 تحقق', '🔄 Verify'),
             'text': T('تأكد أن المستند موجود فعلاً في SOFTECH.', 'Confirm the document really exists in SOFTECH.'),
             'open_hint': T('افتح الفاتورة بعد ترحيلها.', 'Open the invoice after posting it.')},
         ]},
        {'key': 'bundle', 'shell': 'desktop', 'roles': ['admin', 'purchasing'],
         'title': T('حزمة الموزّع: تقسيم وترحيل دفعة', 'Distributor bundle: split and batch post'),
         'summary': T('ارفع PDF فيه عدة فواتير، راجع وأكّد كل فاتورة، ثم رحّلها معاً.',
                      'Upload a PDF with several invoices, review and confirm each, then post them together.'),
         'steps': [
            {'screen': 'invoices.main', 'target': 'invoices-main-bundle-new', 'perm': 'invoices',
             'label': T('+ حزمة جديدة', '+ New bundle'),
             'text': T('ارفع ملف الموزّع؛ النظام يقسّمه لفواتير منفصلة.', 'Upload the distributor file; the system splits it into separate invoices.'),
             'open_hint': T('افتح تبويب «📑 حزم (PDF متعدد)».', 'Open the "📑 Bundles (multi PDF)" tab.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-bundle-invoice', 'perm': 'invoices',
             'label': T('الفواتير المكتشفة', 'Detected invoices'),
             'text': T('كل بطاقة فاتورة منفصلة. «راجع الحدود» = تأكد أن صفحاتها صحيحة. اضغط «فتح للمراجعة».',
                       'Each card is one invoice. "Check the limits" = make sure its pages are right. Press "Open for review".'),
             'open_hint': T('افتح أي حزمة من القائمة.', 'Open any bundle from the list.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-confirm', 'perm': 'invoices',
             'label': T('✓ تأكيد الفاتورة', '✓ Confirm invoice'),
             'text': T('راجع وأكّد كل فاتورة وحدها.', 'Review and confirm each invoice on its own.'),
             'warn': T('الترحيل كدفعة لا يعرض معاينة — المراجعة هنا هي الضمان.', 'Batch posting shows no preview — this review is the safeguard.'),
             'open_hint': T('افتح فاتورة من الحزمة.', 'Open an invoice from the bundle.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-batch-select', 'perm': 'invoices',
             'label': T('تحديد للترحيل كدفعة', 'Select for batch posting'),
             'text': T('في قائمة الفواتير حدّد الفواتير المُأكَّدة.', 'In the invoice list, tick the confirmed invoices.'),
             'open_hint': T('المربع يظهر على بطاقات الفواتير المُأكَّدة فقط.', 'The box shows only on confirmed invoice cards.')},
            {'screen': 'invoices.main', 'target': 'invoices-main-batch-push', 'perm': 'invoices',
             'label': T('⇪ ترحيل المحدد', '⇪ Post selected'),
             'text': T('يرحّلها كلها ويعرض نتيجة كل فاتورة.', 'Posts them all and shows each result.'),
             'warn': T('كل فاتورة تُكتب نهائياً في SOFTECH. محمية ضد التكرار، وأي تحذير يرفضها.',
                       'Each invoice is written as final in SOFTECH. Protected against duplicates; any warning refuses it.'),
             'open_hint': T('يظهر أسفل القائمة بعد التحديد.', 'Shown under the list after selecting.')},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول فواتير الموردين', 'A tour of the Supplier invoices module'),
            'summary': T('من صورة فاتورة المورد لحد ما تبقى مستند شراء في SOFTECH: الرفع، القراءة والمطابقة، المراجعة والتأكيد، ثم المعاينة والترحيل والتحقق.',
                         'From the supplier invoice photo to a purchase document in SOFTECH: upload, reading and matching, review and confirm, then preview, posting and verification.'),
            'roles': ['admin', 'purchasing'],
            'steps': [
                {'target': 'nav-invoices', 'nav': '/invoices',
                 'text': T('«المشتريات» ← «فواتير الموردين».', '"Purchasing" → "Supplier invoices".'),
                 'more': T('هنا بتدخل فواتير الشراء اللي جاية من الموردين بدل ما تتكتب يدوي في SOFTECH.\n'
                           '• الموديول ظاهر للمدير والمشتريات.\n'
                           '• الرحلة: رفع الصورة ← قراءة ومطابقة ← مراجعة وتأكيد ← معاينة وترحيل لـ SOFTECH ← تحقق.',
                           'This is where purchase invoices from suppliers are entered instead of being typed into SOFTECH by hand.\n'
                           '• The module is shown to admin and purchasing.\n'
                           '• The journey: upload the image → reading and matching → review and confirm → preview and post to SOFTECH → verify.')},
                {'target': 'invoices-main-filters', 'route': '/invoices',
                 'text': T('ابدأ يومك بفلتر الحالة: إيه اللي مستني مراجعة وإيه اللي جاهز للترحيل.',
                           'Start your day with the status filter: what needs review and what is ready to post.'),
                 'more': INV_MORE_FILTERS},
                {'target': 'invoices-main-new', 'route': '/invoices',
                 'text': T('«+ فاتورة جديدة» هي أول خطوة لكل فاتورة.', '"+ New invoice" is the first step for every invoice.'),
                 'more': INV_MORE_NEW},
                {'target': 'invoices-main-list', 'route': '/invoices',
                 'text': T('افتح أي فاتورة من الكروت وبعدين اضغط «التالي». لو مفيش فواتير اضغط «إنهاء».',
                           'Open any invoice from the cards, then press "Next". If there are none, press "End".'),
                 'more': INV_MORE_LIST},
                {'target': 'invoices-main-header-card', 'route': '/invoices',
                 'text': T('راجع رأس الفاتورة الأول: المورد والرقم والتاريخ والخصم العام.',
                           'Check the invoice header first: supplier, number, date and global discount.'),
                 'more': INV_MORE_HEADER},
                {'target': 'invoices-main-lines', 'route': '/invoices',
                 'text': T('بعدين السطور: أكّد الصنف المطابق لكل سطر.', 'Then the lines: confirm the matched item on each line.'),
                 'more': INV_MORE_LINES},
                {'target': 'invoices-main-actions', 'route': '/invoices',
                 'text': T('لما السطور تبقى سليمة: «⚠ فحص الانحرافات» ثم «✓ تأكيد الفاتورة».',
                           'When the lines are right: "⚠ Check deviations", then "✓ Confirm invoice".'),
                 'more': T('«فحص الانحرافات» بيطلع تقرير: سطور من غير صنف مطابق، سعر أو كمية صفر، خصم فوق 50%، سعر بعيد عن سعر الكتالوج، صنف مكرر، أو إجمالي مختلف عن إجمالي الفاتورة.\n'
                           '• «✓ تأكيد الفاتورة» بيحوّلها لـ «مُأكَّدة» وبيقفل تعديل السطور، ولسه مفيش حاجة في SOFTECH.\n'
                           '• لو الفاتورة غلط أو مكررة متأكدهاش.',
                           '"Check deviations" reports: lines with no matched item, zero price or quantity, discount above 50%, a price far from the catalog price, a duplicated item, or a total that differs from the invoice total.\n'
                           '• "✓ Confirm invoice" moves it to "Confirmed" and locks line editing; still nothing in SOFTECH.\n'
                           '• If the invoice is wrong or a duplicate, do not confirm it.')},
                {'target': 'invoices-main-actions', 'route': '/invoices',
                 'text': T('بعد التأكيد: «🛡 فحص التحقق» و«⇪ ترحيل إلى ERP».', 'After confirming: "🛡 Validation check" and "⇪ Post to ERP".'),
                 'more': T('«فحص التحقق» بيشغّل قواعد الحفظ بتاعة SOFTECH (حد الائتمان، الأصناف المسموحة، حدود السعر، الصلاحية، رقم الباتش للأصناف التي تشترطه مثل إنتريستو…) من غير ما يكتب حاجة.\n'
                           '• «ترحيل إلى ERP» بيفتح معاينة للمستند: صحّح كل الأخطاء، وعلّم «راجعت التحذيرات وأريد المتابعة»، ثم «⇪ تأكيد الترحيل».\n'
                           '• الترحيل للمدير والمشتريات والمشرف. لو الترحيل مش مفعّل بيشتغل «وضع المعاينة» بس، ولو الفاتورة مرحّلة قبل كده مش بتتكتب تاني.',
                           '"Validation check" runs SOFTECH\'s saving rules (credit limit, allowed items, price limits, expiry, the batch number for items that require it such as Entresto…) without writing anything.\n'
                           '• "Post to ERP" opens a preview of the document: fix every error, tick "I reviewed the warnings and want to continue", then "⇪ Confirm posting".\n'
                           '• Posting is for admin, purchasing and supervisors. If posting is not enabled it works in "preview mode" only, and an invoice already posted is never written twice.')},
                {'target': 'invoices-main-actions', 'route': '/invoices',
                 'text': T('بعد الترحيل: رقم المستند و«🔄 تحقق» و«↩ إنشاء مرتجع».',
                           'After posting: the document number, "🔄 Verify" and "↩ Create return".'),
                 'more': T('الفاتورة المرحّلة بيظهر عليها «✓ مُرحّلة — مستند #…» برقم مستند SOFTECH.\n'
                           '• «🔄 تحقق» بيتأكد إن المستند موجود فعلاً في SOFTECH.\n'
                           '• «↩ إنشاء مرتجع» (لفواتير الشراء) بيعمل مسودة مرتجع مورد مربوطة بنفس المستند، تعدّل كمياتها وبعدين تأكدها وترحّلها بنفس الطريقة.\n'
                           '• لو ظهر «فشل الترحيل» اقرأ السبب واضغط «↻ إعادة الترحيل».',
                           'A posted invoice shows "✓ Posted — document #…" with the SOFTECH document number.\n'
                           '• "🔄 Verify" checks the document really exists in SOFTECH.\n'
                           '• "↩ Create return" (purchase invoices) makes a supplier-return draft linked to the same document; trim its quantities, then confirm and post it the same way.\n'
                           '• If "Posting failed" shows, read the reason and press "↻ Retry posting".')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'invoices.main',
        'routes': ['/invoices'],
        'title': T('فواتير الموردين', 'Supplier invoices'),
        'summary': T('قائمة الفواتير بحالاتها، وإدخال فاتورة جديدة، ومراجعة سطورها وترحيلها، وإنشاء مسودة مرتجع مورد من فاتورة.',
                     'The invoice list by status, entering a new invoice, reviewing its lines and posting it, and creating a supplier-return draft from an invoice.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'steps': [
            T('«فاتورة جديدة»: الفرع والمورد ونوع المستند (شراء أو مرتجع) وارفع الصورة.', '"New invoice": branch, supplier and document type (purchase or return), and upload the image.'),
            T('حزمة فواتير (PDF متعدد): لو عندك ملف PDF فيه عدة فواتير (مثل ملف الموزّع اليومي)، ارفعه كـ«حزمة» — النظام يقسّمه آلياً إلى الفواتير المنفصلة التي يحتويها (بالاعتماد على رقم الفاتورة وعدّاد الصفحات «١/١» وكتلة الإجماليات) ثم ينشئ فاتورة لكل واحدة في قائمة المراجعة. التقسيم استرشادي ويظهر بالكامل للمراجعة، وتُراجَع وتُعتمد كل فاتورة قبل الترحيل.',
              'Invoice bundle (multi-invoice PDF): if you have one PDF containing several invoices (e.g. the distributor\'s daily file), upload it as a "bundle" — the system automatically splits it into the separate invoices it contains (using the invoice number, the "1/1" page counter and the totals block) and creates one invoice per detected document in the review queue. The split is advisory and fully shown for review; every invoice is reviewed and approved before posting.'),
            T('راجع بيانات الرأس (المورد، رقم وتاريخ الفاتورة، الخصم العام).', 'Check the header (supplier, invoice number and date, global discount).'),
            T('لكل سطر: تحقق من الصنف المطابق والكمية وسعر الوحدة والخصم. السطور ذات «ثقة استخراج OCR» المنخفضة أو «الاسم العربي والعلمي أشارا لصنفين مختلفين» تحتاج انتباهاً. «إعادة OCR» لو القراءة سيئة.',
              'For each line: check the matched item, quantity, unit price and discount. Lines with low "OCR confidence" or "Arabic and scientific names point to different items" need attention. "Re-run OCR" if the reading is poor.'),
            T('«⊞ جدول SofTech»: جدول مطابق لشاشة «مشتريات من الموردين» بكامل أعمدتها — رصيد حالي، الباتش، سعر الجمهور والسعر الأساسي (من الكتالوج، غير قابلة للتعديل)، ثلاثة خصومات (أساسي ثم إضافي ثم خاص، متتالية)، نوع الضريبة ونسبتها ومبلغها (أي منهما يحسب الآخر)، «الضريبة من التكلفة»، تكلفة الوحدة بدون/بالضريبة، والإجماليات. أي تعديل يعيد حساب الخانات المرتبطة بنفس منطق SofTech (التكلفة = السعر الأساسي × (١−خصم١)(١−خصم٢)(١−خصم٣))؛ وتعديل التكلفة يعيد اشتقاق الخصم الأساسي. يعرض أيضاً تنبيه تغيّر سعر البيع، واختيار الصنف، وسطر البونص (10+1) الذي يُرحَّل كسطرين.',
              '"⊞ SofTech grid": the full native «مشتريات من الموردين» column set — current stock, batch, public & base price (from the catalog, read-only), three compounding discounts (basic → extra → special), tax type/percent/amount (either computes the other), "tax from cost", unit cost with/without tax, and the totals. Editing any cell recomputes the dependents with SofTech\'s own math (cost = base × (1−d1)(1−d2)(1−d3)); editing the cost back-solves the basic discount. It also shows the retail-price-change flag, the item picker, and the bonus line (10+1) posting as two lines. The two fixed-margin columns (هامش صيدلى / هامش موزع) are display-only: they do NOT enter the line cost (SofTech stores the net discounted cost), but the distributor margin adds on top at the invoice total.'),
            T('عمودا «هامش صيدلى» و«هامش موزع»: للعرض فقط. تكلفة السطر تبقى صافية (كما يخزّنها SofTech)؛ ولا يتغيّر إجمالي السطر. هامش الموزع يُضاف فوق إجمالي الفاتورة (وغالباً يساوي هامش الصيدلى).',
              'The "pharmacist margin" and "distributor margin" columns are display-only. The line cost stays net (as SofTech stores it) and the line total is unchanged; the distributor margin is added on top of the invoice total (and usually equals the pharmacist margin).'),
            T('«الصلاحية» و«الباتش» قابلان للتعديل مباشرةً في الجدول (يُحفظان عند الخروج من الخانة). أما الكمية والأسعار والخصومات فتُحسب فوراً.',
              'The "expiry" and "batch" cells are directly editable in the grid (saved on blur). Quantity, prices and discounts recompute live.'),
            T('سعر الصيدلي لأصناف الهامش يُحسب كما يطبعه الموزّع: (سعر الجمهور − هامش الصيدلي − هامش الموزع) × (١ − الخصم). يُستخدم إن لم تُقرأ التكلفة، وإن قُرئت تكلفة لا تطابقه يظهر تنبيه «الصافي لا يطابق الهوامش والخصم». وإن جاءت أرقام السطر مُزاحة في القراءة (مثلاً الإجمالي في خانة الخصم) يُعاد ترتيبها تلقائياً مع تنبيه للمراجعة. وإن بَعُد سعر الجمهور كثيراً عن الكتالوج يظهر تنبيه «قد تكون أرقام سطر آخر».',
              'The pharmacist price of margin items is computed the way the distributor prints it: (public price − pharmacist margin − distributor margin) × (1 − discount). It is used when the cost was not read; when a read cost disagrees, the line is flagged "net does not match margins and discount". When a line\'s numbers were read shifted (e.g. the total in the discount cell) they are put back automatically and flagged for review. A public price far from the catalog is flagged "may be another row\'s numbers".'),
            T('الخصم الأساسي وتكلفة الوحدة الصافية مرتبطان دائماً: تعديل أحدهما يغيّر الآخر فوراً. تعديل «خصم إضافي» أو «خصم خاص» يُبقي التكلفة الصافية كما هي (المقروءة من الفاتورة) ويمتصّ «الخصم الأساسي» الفرق. الخصم الإضافي لا يتغيّر تلقائياً أبداً — فقط إذا كتبته أو قُرئ من الفاتورة.',
              'The basic discount and the net unit cost are always linked: changing one updates the other immediately. Changing the "extra" or "special" discount keeps the net cost (as read from the invoice) and the basic discount absorbs the difference. The extra discount is never changed automatically — only when you type it or it is read from the invoice.'),
            T('الصلاحية تُكتب يوم/شهر/سنة كما في SofTech، والفاصل نقطة أو شَرطة أو / (مثل 5-5-28 أو 09.09.2029)، والسنة رقمان أو أربعة. إن كانت الفاتورة تذكر الشهر والسنة فقط يصبح اليوم = الشهر (09.2029 ← 09/09/2029) منعاً للالتباس. التاريخ غير المفهوم تُحدَّد خانته بالأحمر ولا يُحفظ.',
              'Expiry is typed day/month/year like SofTech, with a dot, dash or / as separator (e.g. 5-5-28 or 09.09.2029) and a 2- or 4-digit year. When the invoice gives only month and year, the day is set equal to the month (09.2029 → 09/09/2029) to avoid confusion. A date that cannot be read is outlined red and not saved.'),
            T('التنقل بلوحة المفاتيح كما في SofTech: داخل أي خانة، السهمان ↑↓ ينقلانك لنفس العمود في السطر السابق/التالي، وTab للخانة التالية في السطر ثم أول خانة في السطر التالي، وShift+Tab للخلف حتى بداية السطر ثم السطر السابق. عند الدخول للخانة تُحدَّد قيمتها فتكتب فوقها مباشرة.',
              'SofTech-style keyboard: inside any cell, ↑↓ move to the same column on the previous/next line, Tab goes to the next cell on the line then the first cell of the next line, and Shift+Tab goes back to the start of the line then the previous line. Entering a cell selects its value so you can type over it.'),
            T('الضريبة: يُؤخذ معدّل ض.ق.م من الفاتورة نفسها أولاً، فإن خالف بيانات الكتالوج (التي قد تكون غير محدَّثة) يُستخدم معدّل الفاتورة ويظهر تنبيه «ضريبة الصنف من الفاتورة تخالف الكتالوج — راجعها» لتتأكد. النظام يتبع الطريقة المعتمدة (الضريبة خارج التكلفة): تكلفة الوحدة صافية بدون ضريبة، وتُضاف الضريبة في الإجماليات بالأسفل.',
              'VAT: the invoice\'s own VAT rate is taken first; if it disagrees with the catalog (which can be stale) the invoice rate is used and the line is flagged "item VAT from invoice differs from catalog — review it" so you confirm. The system follows the house method (VAT outside cost): the unit cost is net of VAT, and VAT is added in the bottom totals.'),
            T('أسفل الجدول إجماليات مطابقة لشاشة SofTech: «الإجمالي بدون ضريبة» و«قيمة هامش الموزع» (لموردي الهامش) و«خارج التكلفة (ض.ق.م)» و«الإجمالي النهائي»، مع مقارنة بإجمالي فاتورة الورق (✓ مطابق أو الفرق) لتتحقق قبل الترحيل.',
              'Below the grid are totals matching the SofTech screen: "total before tax", "distributor-margin value" (for margin suppliers), "VAT outside cost" and "final total", compared against the printed paper-invoice total (✓ matches, or the gap) so you can verify before posting.'),
            T('هامش الموزع: بعض الموردين (مثل فارما أوفرسيز) يضيفون «هامش ثابت للموزع» إلى تكلفة الصنف، فتُرحَّل «التكلفة للترحيل» = تكلفة الوحدة الصافية + هامش الموزع (وهي القيمة المميّزة بالأصفر التي تدخل SofTech). موردون آخرون (مثل رامكو) يعرضون الهامش فقط دون إضافته. يحدِّد النظام ذلك تلقائياً من إجمالي الفاتورة (أو بإعداد للمورد). الصنف الخاضع للضريبة لا يكون له هامش والعكس.',
              'Distributor margin: some suppliers (e.g. PharmaOverseas) add a "fixed distributor margin" to the item cost, so "cost to post" = net unit cost + distributor margin (the amber value that enters SofTech). Others (e.g. RAMCO) only display the margin without adding it. The system decides this automatically from the invoice total (or a per-supplier setting). A VAT-taxed item never has a margin and vice-versa.'),
            T('لتصحيح مطابقة صنف: اضغط ✎ لتعديل الاسم المقروء، أو «🔍 اختر/تغيير» وابحث بالاسم أو بكود الصنف واختر الصنف الصحيح — نفس بحث الأصناف في كل النظام.',
              'To fix an item match: press ✎ to edit the read name, or "🔍 pick/change" and search by name or by item code and choose the right item — the same item search used across the whole system.'),
            T('«✓ تأكيد الجاهزة»: يؤكّد دفعةً واحدة كل السطور الجاهزة (مطابَقة ≥٨٥٪ ولها سعر وكمية وبدون تنبيه مراجعة) ويتعلّم ربطها للفواتير القادمة، فلا يتبقّى سوى السطور القليلة التي تحتاج مراجعة يدوية — لتسريع المراجعة.',
              '"✓ Confirm ready lines": one click confirms every ready line (matched ≥85%, priced, has quantity, no review flag) and learns its mapping for future invoices, leaving only the few lines that need manual review — to speed up review.'),
            T('رصد التكرار تلقائياً: بمجرد انتهاء قراءة الفاتورة يفحص النظام SofTech في الخلفية، فتظهر في قائمة الفواتير شارة «⛔ مكرّرة» أو «⚠ تكرار محتمل» قبل أن تفتحها — لتتجنّب العمل على فاتورة مُدخلة من قبل.',
              'Automatic duplicate detection: as soon as an invoice is read, the system checks SofTech in the background, so the invoice list shows a "⛔ duplicate" or "⚠ likely duplicate" badge before you even open it — so you avoid working on an already-entered invoice.'),
            T('«فحص الانحرافات» ثم «تأكيد» الفاتورة.', '"Check deviations" then "Confirm" the invoice.'),
            T('«معاينة الترحيل إلى ERP»: صحّح كل الأخطاء، راجع التحذيرات وعلّم «راجعت التحذيرات»، ثم «تأكيد الترحيل».', '"Preview ERP posting": fix every error, review warnings and tick "I reviewed the warnings", then "Confirm posting".'),
            T('ترحيل دفعة: من قائمة الفواتير حدّد عدة فواتير مُأكَّدة (بمربع الاختيار) ثم «⇪ ترحيل المحدد» لترحيلها معاً — تُراجَع كل فاتورة على حدة أولاً، وتُرحَّل الدفعة دفعة واحدة. كل فاتورة لها حماية ضد الترحيل المزدوج، وفشل فاتورة لا يوقف الباقي.',
              'Batch posting: from the invoice list, tick several confirmed invoices then "⇪ Post selected" to post them together — each is reviewed individually first, then the group is posted in one go. Every invoice is protected against double-posting, and one failing invoice does not stop the rest.'),
            T('فحص التكرار (زر «🔎 فحص التكرار») — فحص شامل على SofTech قبل الترحيل: يبحث في مستندات المورد الأخيرة ويقارن بعدّة عوامل معاً — رقم فاتورة المورد (مطابق أو شبه مطابق)، الإجمالي النهائي، الأصناف وعددها، تاريخ الفاتورة، وتاريخ الحفظ القريب — ويعطي كل مستند مشابه نسبة تطابق، فيُكتشف التكرار حتى لو اختلف رقم الفاتورة بسبب القراءة الضوئية. يعمل الفحص أيضاً تلقائياً داخل «معاينة الترحيل» قبل الحفظ، والترحيل محمي ضد التكرار ويطلب تأكيداً إضافياً.',
              'Duplicate check ("🔎 Duplicate check" button) — a thorough SofTech check before posting: it scans the supplier\'s recent documents and matches on several factors together — supplier invoice number (exact or partial), final total, items and their count, invoice date, and a nearby save date — scoring each similar document, so a re-entry is caught even if the OCR\'d invoice number differs. It also runs automatically inside "Preview posting" before saving; posting is protected against duplicates and asks for an extra confirmation.'),
            T('معالجة الملفات الصعبة: عند رفع حزمة يتخطّى النظام الصفحات الفارغة، ويصحّح اتجاه الصفحات المقلوبة، ويضع تنبيهات على الفواتير الناقصة أو المقصوصة أو منخفضة الجودة (خط يد) لتراجعها بعناية.',
              'Messy files: when a bundle is uploaded the system skips blank pages, auto-rotates sideways pages, and flags incomplete, paper-cut or low-quality (handwriting) invoices so you review them carefully.'),
        ],
        'tips': [
            T('كل إجراء بيتحقق من صلاحيتك على السيرفر (مصفوفة الصلاحيات، موديول الفواتير): التعديل وتشغيل القراءة الآلية يحتاجوا «تعديل»، «تأكيد» و«رفض» وعمل مرتجع يحتاجوا «اعتماد»، والإرسال لـ SOFTECH يحتاج «إنهاء».',
              'Every action is checked on the server (Permissions Matrix, invoices module): editing and running OCR need "edit", "Confirm", "Reject" and creating a return need "approve", and sending to SOFTECH needs "finalize".'),
            T('بعد دخول الفاتورة طابور الترحيل أو ترحيلها إلى SOFTECH لا يُعدَّل رأسها ولا سطورها — التصحيح بمرتجع.',
              'Once an invoice is queued for or posted to SOFTECH its header and lines cannot be edited — correct it with a return.'),
            T('تعديل فاتورة «مُأكَّدة» (أو فشل ترحيلها) يرجعها «قيد المراجعة» — أكّدها من جديد قبل الترحيل.',
              'Editing a "confirmed" (or push-failed) invoice puts it back to "review" — confirm it again before sending.'),
            T('لو ظهر «سيتغيّر كود المورد لهذا الصنف» فهذا تعارض في ربط كود المورد بالأصناف — اعتمده فقط لو متأكد.', 'If "this item\'s supplier code will change" appears, it is a supplier-code mapping conflict — approve only if you are sure.'),
            T('لو الترحيل غير مُفعّل تعمل الشاشة في «وضع المعاينة» فقط.', 'If posting is not enabled, the screen works in "preview mode" only.'),
            T('محرك القراءة: «تلقائي» يقرأ أولاً بمحرّك مجاني محلي (Tesseract بالعربية — سريع ودقيق على الفواتير المطبوعة) وبه قوالب أعمدة جاهزة للموزّعين الكبار (رامكو، فارما أوفرسيز) تستخرج الاسم والسعر والخصم والصلاحية؛ ولا يلجأ إلى Gemini (المدفوع) إلا إذا كانت النتيجة المجانية ضعيفة — لتحقيق أقصى استخراج مجاني مع ضمان الجودة. يمكن فرض محرّك معيّن عند رفع الحزمة أو إعادة القراءة. راجع الأسعار دائماً.',
              'OCR engine: "Auto" reads first with a free local engine (Tesseract Arabic — fast and accurate on printed invoices) with ready-made column templates for the big distributors (Ramco, PharmaOverseas) that extract name, price, discount and expiry; it escalates to Gemini (paid) only when the free result is weak — maximizing free extraction while guaranteeing quality. You can force a specific engine when uploading a bundle or re-running OCR. Always verify prices.'),
        ],
        'related': ['purchasing.history', 'finance.reconciliation'],
        'tour': [
            {'target': 'invoices-main-new', 'label': T('+ فاتورة جديدة', '+ New invoice'),
             'text': T('يفتح نموذج فاتورة مورد: الفرع (إلزامي) والمورد ورقم الفاتورة وصورة أو PDF الفاتورة.',
                       'Opens the supplier-invoice form: branch (required), supplier, invoice number and the invoice photo or PDF.'),
             'when': T('بعد «إنشاء الفاتورة» يقرأ النظام الصورة (OCR) ويطابق السطور، ثم تفتح الفاتورة للمراجعة.',
                       'After "Create invoice" the system reads the image (OCR) and matches the lines, then the invoice opens for review.'),
             'more': T(
                 'استخدمه لما توصلك فاتورة شراء ورقية أو PDF من مورد بدل ما تكتبها بإيدك في SOFTECH.\n• بيفتح نافذة «فاتورة مورد جديدة»: الفرع (إجباري)، اسم المورد، رقم الفاتورة، التاريخ، وصورة أو PDF الفاتورة.\n• بعد الحفظ الفاتورة بتتفتح على طول، والنظام بيقرأ الصورة (OCR) ويطابق كل سطر بصنف من الكتالوج.\n• لسه مفيش أي حاجة اتكتبت في SOFTECH في الخطوة دي.',
                 'Use it when a paper or PDF purchase invoice arrives from a supplier, instead of typing it into SOFTECH by hand.\n• It opens the "New supplier invoice" window: branch (required), supplier name, invoice number, date, and the invoice image or PDF.\n• After saving, the invoice opens straight away and the system reads the image (OCR) and matches each line to a catalog item.\n• Nothing is written to SOFTECH at this step.')},
            {'target': 'invoices-main-bundle-new', 'label': T('+ حزمة جديدة', '+ New bundle'),
             'text': T('لملف PDF فيه عدة فواتير: يقسّمه النظام لفواتير منفصلة، كل واحدة تُراجَع وحدها.',
                       'For one PDF holding several invoices: the system splits it into separate invoices, each reviewed on its own.'),
             'when': T('ملف الموزّع اليومي. افتح الحزمة وراجع حدود كل فاتورة «راجع الحدود» قبل العمل عليها.',
                       'The daily distributor file. Open the bundle and check any invoice marked "check the limits" before working on it.'),
             'open_hint': T('افتح تبويب «📑 حزم (PDF متعدد)».', 'Open the "📑 Bundles (multi PDF)" tab.')},
            {'target': 'invoices-main-filters', 'label': T('الفرع · الحالة · تحتاج مراجعة', 'Branch · status · needs review'),
             'text': T('صفِّ القائمة بالفرع والحالة، و«⚠ تحتاج مراجعة» أو «✓ نظيفة».',
                       'Filter the list by branch and status, and "⚠ needs review" or "✓ clean".'),
             'when': T('ابدأ بـ«تحتاج مراجعة» — دي الفواتير اللي فيها سطور ضعيفة القراءة أو المطابقة.',
                       'Start with "needs review" — those invoices have lines with weak reading or matching.'),
             'more': T(
                 'اختار فرع و/أو حالة عشان تركّز على شغلك.\n• «قيد المراجعة»: فواتير محتاجة حد يراجع سطورها.\n• «مُأكَّدة» و«فشل الترحيل»: جاهزة للمعاينة والترحيل أو محتاجة إعادة محاولة.\n• «مُرحّلة إلى ERP»: خلصت وبقت مستند في SOFTECH.',
                 'Pick a branch and/or a status to focus on your work.\n• "In review": invoices whose lines need checking.\n• "Confirmed" and "Posting failed": ready for the preview and posting, or need a retry.\n• "Posted to ERP": done and now a SOFTECH document.')},
            {'target': 'invoices-main-card', 'label': T('بطاقة الفاتورة', 'Invoice card'),
             'text': T('المورد والفرع والحالة وعدد السطور المؤكدة. شارة «⛔ مكرّرة» أو «⚠ تكرار محتمل» من فحص SOFTECH التلقائي.',
                       'Supplier, branch, status and confirmed lines. A "⛔ duplicate" or "⚠ likely duplicate" badge comes from the automatic SOFTECH check.'),
             'when': T('اضغط البطاقة لفتح الفاتورة ومراجعة سطورها.', 'Click the card to open the invoice and review its lines.'),
             'warn': T('بطاقة عليها «⛔ مكرّرة» سبق حفظها في SOFTECH — لا تكمل عليها قبل التأكد.',
                       'A card marked "⛔ duplicate" was already saved in SOFTECH — do not continue before checking.')},
            {'target': 'invoices-main-confirm-ready', 'label': T('✓ تأكيد الجاهزة', '✓ Confirm ready lines'),
             'text': T('يؤكد مرة واحدة كل سطر مطابَق بثقة عالية وله سعر وكمية وبدون تنبيه، ويتعلّم الربط للفواتير القادمة.',
                       'Confirms in one go every line matched with high confidence, priced, with a quantity and no flag, and learns the mapping.'),
             'when': T('أول خطوة في المراجعة؛ يتبقى لك السطور القليلة اللي تحتاج نظرك.', 'The first review step; only the few lines that need you are left.'),
             'open_hint': T('افتح فاتورة «قيد المراجعة» فيها سطور غير مؤكدة.', 'Open an "In review" invoice with unconfirmed lines.')},
            {'target': 'invoices-main-view', 'label': T('بطاقات · ⊞ جدول SofTech', 'Cards · ⊞ SofTech grid'),
             'text': T('الجدول نفس أعمدة شاشة «مشتريات من الموردين» مع تعديل مباشر وإجماليات تقارن بإجمالي الورق.',
                       'The grid has the same columns as the SofTech purchase screen, with direct edits and totals compared to the paper total.'),
             'when': T('راجع الإجمالي النهائي مقابل الفاتورة الورقية قبل التأكيد.', 'Check the final total against the paper invoice before confirming.'),
             'open_hint': T('افتح أي فاتورة فيها سطور.', 'Open any invoice that has lines.')},
            {'target': 'invoices-main-confirm', 'label': T('✓ تأكيد الفاتورة', '✓ Confirm invoice'),
             'text': T('ينقل الفاتورة إلى «مُأكَّدة» ويحفظ ربط أصناف المورد للمرات القادمة. لا شيء يُكتب في SOFTECH.',
                       'Moves the invoice to "Confirmed" and saves the supplier item mappings. Nothing is written to SOFTECH.'),
             'when': T('بعد مراجعة كل السطور. بعدها يظهر زر «⇪ ترحيل إلى ERP».', 'After reviewing every line. The "⇪ Post to ERP" button then appears.'),
             'warn': T('بعد التأكيد تُقفل السطور والرأس للتعديل — راجع الكميات والأسعار أولاً.',
                       'After confirming, the lines and header are locked — check quantities and prices first.'),
             'open_hint': T('افتح فاتورة «قيد المراجعة».', 'Open an "In review" invoice.')},
            {'target': 'invoices-main-push', 'label': T('⇪ ترحيل إلى ERP', '⇪ Post to ERP'),
             'text': T('يفتح «معاينة الترحيل»: ما سيُكتب بالضبط، وقواعد حفظ SOFTECH، وفحص التكرار. الفتح نفسه لا يكتب شيئاً.',
                       'Opens the posting preview: exactly what will be written, the SOFTECH save rules and the duplicate check. Opening it writes nothing.'),
             'when': T('يظهر للفاتورة المُأكَّدة أو التي فشل ترحيلها («↻ إعادة الترحيل»).', 'Shown for a confirmed invoice, or one whose posting failed ("↻ Re-post").'),
             'warn': T('الأخطاء في المعاينة تمنع الترحيل؛ صحّحها أولاً ولا تتجاوز تنبيه التكرار بلا سبب.',
                       'Errors in the preview block posting; fix them first and never skip a duplicate warning without a reason.'),
             'open_hint': T('افتح فاتورة «مُأكَّدة».', 'Open a "Confirmed" invoice.')},
            {'target': 'invoices-main-push-confirm', 'label': T('⇪ تأكيد الترحيل', '⇪ Confirm posting'),
             'text': T('يكتب مستند شراء نهائي (أو مرتجع) في SOFTECH: يدخل المخزون وتتغير التكلفة ورصيد المورد.',
                       'Writes a final purchase (or return) document into SOFTECH: stock is received and cost and supplier balance change.'),
             'when': T('بعد تصحيح الأخطاء وتعليم «راجعت التحذيرات». تظهر رسالة برقم المستند.', 'After fixing errors and ticking "I reviewed the warnings". A message shows the document number.'),
             'warn': T('مستند نهائي في SOFTECH. محمي ضد الترحيل المزدوج، ولو الترحيل غير مُفعّل تبقى معاينة فقط.',
                       'A final SOFTECH document. Protected against double posting; if posting is not enabled it stays a preview only.'),
             'open_hint': T('يظهر داخل نافذة المعاينة بعد «⇪ ترحيل إلى ERP».', 'Shown inside the preview window after "⇪ Post to ERP".')},
            {'target': 'invoices-main-verify', 'label': T('🔄 تحقق', '🔄 Verify'),
             'text': T('قراءة فقط: يتأكد أن المستند ما زال موجوداً في SOFTECH، وهل له مرتجع مورد.',
                       'Read only: checks the document still exists in SOFTECH, and whether it has a supplier return.'),
             'when': T('بعد الترحيل، أو لو شككت أن أحداً حذف المستند من SOFTECH.', 'After posting, or if you suspect someone deleted the document in SOFTECH.'),
             'open_hint': T('افتح فاتورة «مُرحَّلة إلى ERP».', 'Open a "Posted to ERP" invoice.')},
            {'target': 'invoices-main-return', 'label': T('↩ إنشاء مرتجع', '↩ Create return'),
             'text': T('ينشئ مسودة مرتجع مورد مرتبطة بالمستند الأصلي، بنفس السطور، في «قيد المراجعة».',
                       'Creates a supplier-return draft linked to the original document, with the same lines, in "In review".'),
             'when': T('عدّل الكميات للمرتجع الجزئي، ثم أكّد ورحّل المرتجع مثل أي فاتورة.', 'Trim quantities for a partial return, then confirm and post it like any invoice.'),
             'warn': T('المسودة لا تكتب شيئاً؛ ترحيلها لاحقاً يُخرج الكميات من المخزون في SOFTECH.',
                       'The draft writes nothing; posting it later takes the quantities out of stock in SOFTECH.'),
             'open_hint': T('افتح فاتورة شراء «مُرحَّلة إلى ERP».', 'Open a "Posted to ERP" purchase invoice.')},
            {'target': 'invoices-main-batch-push', 'label': T('⇪ ترحيل المحدد', '⇪ Post selected'),
             'text': T('يرحّل كل الفواتير المحددة إلى SOFTECH مرة واحدة ويعرض نتيجة كل فاتورة.',
                       'Posts every selected invoice to SOFTECH in one go and shows the result of each.'),
             'when': T('بعد مراجعة كل فاتورة وحدها. فشل فاتورة لا يوقف الباقي.', 'After reviewing each invoice on its own. One failure does not stop the rest.'),
             'warn': T('بدون نافذة معاينة: كل فاتورة تُكتب نهائياً. أي فاتورة بها أخطاء أو تحذيرات تُرفض.',
                       'No preview window: each invoice is written as final. Any invoice with errors or warnings is refused.'),
             'open_hint': T('حدّد مربع الاختيار على بطاقات الفواتير المُأكَّدة.', 'Tick the checkbox on confirmed invoice cards.')},
            {'target': 'invoices-main-list',  # from the GitHub-side tour
             'label': T('قائمة الفواتير', 'Invoice list'),
             'when': T('لمتابعة الفواتير المرفوعة ومعرفة اللي لسه محتاج مراجعة.', 'To follow uploaded invoices and spot those still needing review.'),
             'text': T('الفواتير مع حالتها وعدد السطور المؤكدة؛ اضغط فاتورة لفتحها.',
                       'Invoices with status and confirmed lines; click one to open it.'),
             'more': T(
                 'كل كارت فاتورة فيه المورد والحالة ونسبة السطور المؤكدة من إجمالي السطور.\n• اضغط الكارت عشان تفتح الفاتورة في نفس الصفحة وتراجعها.\n• النسبة الواطية معناها لسه فيه سطور الصنف بتاعها محتاج تأكيد.',
                 'Each invoice card shows the supplier, the status and how many lines are confirmed out of all lines.\n• Click a card to open the invoice on the same page and review it.\n• A low percentage means some lines still need their item confirmed.')},
            {'target': 'invoices-main-actions',  # from the GitHub-side tour
             'label': T('أزرار الفاتورة', 'Invoice actions'),
             'when': T('بعد ما تفتح الفاتورة وتراجع سطورها.', 'After opening the invoice and reviewing its lines.'),
             'text': T('داخل الفاتورة: أزرار تتغير بالحالة مثل «⚠ فحص الانحرافات» و«✓ تأكيد الفاتورة»؛ الترحيل لـ ERP بمعاينة وصلاحية.',
                       'Inside an invoice: buttons change with status, e.g. "⚠ Check deviations" and "✓ Confirm"; ERP posting needs a preview and permission.'),
             'more': T(
                 'الأزرار هنا بتظهر حسب حالة الفاتورة:\n• «⚠ فحص الانحرافات» يطلع تقرير بالسطور المشكوك فيها (سعر بعيد عن الكتالوج، خصم عالي، صنف مكرر…)، و«🔄 إعادة OCR» لو القراءة وحشة.\n• «✓ تأكيد الفاتورة» بيغيّر الحالة لـ «مُأكَّدة» بس — مش بيكتب في SOFTECH.\n• «🛡 فحص التحقق» ثم «⇪ ترحيل إلى ERP» بيفتح معاينة: الأخطاء بتمنع الترحيل والتحذيرات محتاجة «راجعت التحذيرات وأريد المتابعة». الترحيل للمدير والمشتريات والمشرف، ولو الفاتورة اترحّلت قبل كده مش بتتكتب تاني.',
                 'The buttons here depend on the invoice status:\n• "⚠ Check deviations" lists suspicious lines (price far from the catalog, high discount, duplicated item…), and "🔄 Re-run OCR" helps when the reading is poor.\n• "✓ Confirm invoice" only changes the status to "Confirmed" — it does not write to SOFTECH.\n• "🛡 Validation check" then "⇪ Post to ERP" opens a preview: errors block posting and warnings need "I reviewed the warnings". Posting is for admin, purchasing and supervisors, and an invoice already posted is never written twice.')},
            {'target': 'invoices-main-header-card',  # from the GitHub-side tour
             'label': T('بيانات رأس الفاتورة', 'Invoice header'),
             'when': T('لو المورد أو الرقم أو التاريخ أو الخصم اتقرا غلط.', 'If the supplier, number, date or discount was read wrongly.'),
             'text': T('داخل الفاتورة: بيانات الرأس (المورد، الرقم، التاريخ، الخصم، الإجمالي) و«تعديل» لو قابلة للتعديل.',
                       'Inside an invoice: the header (supplier, number, date, discount, total) and "Edit" when editable.'),
             'more': T(
                 'دي بيانات رأس الفاتورة زي ما اتقرت: المورد، رقم وتاريخ الفاتورة، الخصم العام (نسبة أو مبلغ) والإجمالي.\n• قارنها بالورقة الأصلية قبل التأكيد.\n• «تعديل» بيظهر بس طول ما الفاتورة لسه قابلة للتعديل (قبل التأكيد).',
                 'This is the invoice header as it was read: supplier, invoice number and date, global discount (percent or amount) and total.\n• Compare it with the paper original before confirming.\n• "Edit" shows only while the invoice can still be edited (before confirming).')},
            {'target': 'invoices-main-lines',  # from the GitHub-side tour
             'label': T('سطور الفاتورة', 'Invoice lines'),
             'when': T('قبل التأكيد: راجع كل سطر والصنف المطابق له.', 'Before confirming: check every line and its matched item.'),
             'text': T('داخل الفاتورة: سطورها؛ راجع الصنف المطابق والكمية والسعر لكل سطر.',
                       'Inside an invoice: its lines; check the matched item, quantity and price on each.'),
             'more': T(
                 'كل سطر: الصنف اللي النظام طابقه، الكمية، سعر الوحدة والخصم، ودرجة ثقة القراءة.\n• السطور منخفضة الثقة أو اللي الاسم العربي والعلمي فيها أشاروا لصنفين مختلفين محتاجة انتباهك.\n• بالكيبورد: ↑↓ للتنقل، Enter يأكّد الصنف المقترح وينقلك للسطر اللي بعده، M يعرض اقتراحات المطابقة.',
                 'Each line: the item the system matched, quantity, unit price and discount, and the reading confidence.\n• Lines with low confidence, or where the Arabic and scientific names point to different items, need your attention.\n• Keyboard: ↑↓ to move, Enter confirms the suggested item and moves to the next line, M shows match suggestions.')},
        ],
        'updated': '2026-10-31',
        'change_note': T('الصلاحية بأي فاصل، التنقل كما في SofTech، ربط الخصم بالصافي، وتصحيح قراءة الهوامش والأعمدة', 'Expiry with any separator, SofTech-style movement, discount⟷net link, and margin/column-shift reading fixes'),
    },
]
