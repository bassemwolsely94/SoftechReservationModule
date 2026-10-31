from . import T

_NEW = T('اضغط «+ مستند جديد» تظهر النافذة.', 'Press "+ New document" to open the window.')
_DOC = T('افتح أي مستند من القائمة.', 'Open any document from the list.')
_LINES = T('افتح عرض أسعار أو فاتورة بيع (مش شبكة توزيع).', 'Open a quotation or sales invoice (not an allocation grid).')
_GRID = T('افتح مستند «شبكة توزيع» له جهة.', 'Open an "allocation grid" document that has a client.')

MODULE = {
    'key': 'commerce', 'group': 'finance', 'icon': '🧩',
    'title': T('المستندات التجارية', 'Commercial documents'),
    'summary': T(
        'إصدار مستندات تجارية خارج نقطة البيع: عروض أسعار، فواتير بيع لعميل تجزئة/توصيل، و«شبكات توزيع» للمستشفيات والجهات متعددة الفروع '
        '(صنف بسعر موحّد وكمية لكل فرع من فروع الجهة). الأسعار شاملة الضريبة، ويُحسب جزء ضريبة 14% تلقائياً للأصناف الخاضعة. التصدير Excel. لا يكتب في SOFTECH.',
        'Issue commercial documents outside the POS: quotations, sales invoices for a retail/delivery customer, and "allocation grids" for hospitals and multi-branch clients '
        '(an item at one unit price with a quantity per client branch). Prices include VAT; the 14% VAT portion is calculated automatically for taxable items. Export to Excel. Nothing is written to SOFTECH.'),
    'journeys': [
        {'key': 'quotation', 'shell': 'desktop',
         'title': T('عرض أسعار من الصفر للتصدير', 'A quotation from scratch to export'),
         'summary': T('أنشئ المستند، ضيف البنود بأسعار شاملة الضريبة، راجع الإجماليات، وصدّر Excel.',
                      'Create the document, add lines at VAT-inclusive prices, check the totals and export to Excel.'),
         'steps': [
            {'screen': 'commerce.documents', 'target': 'commerce-documents-new', 'perm': 'commerce',
             'label': T('+ مستند جديد', '+ New document'),
             'text': T('ابدأ مستند جديد.', 'Start a new document.')},
            {'screen': 'commerce.documents', 'target': 'commerce-documents-type', 'perm': 'commerce',
             'label': T('النوع *', 'Type *'),
             'text': T('اختار «عرض أسعار» أو فاتورة بيع أو شبكة توزيع.', 'Pick a quotation, a sales invoice or an allocation grid.'),
             'open_hint': _NEW},
            {'screen': 'commerce.documents', 'target': 'commerce-documents-recipient', 'perm': 'commerce',
             'label': T('الجهة (اختياري)', 'Client (optional)'),
             'text': T('اختار الجهة، أو ضيف جهة جديدة من الخانة اللي تحتها.', 'Pick the client, or add a new one in the box below.'),
             'open_hint': _NEW},
            {'screen': 'commerce.documents', 'target': 'commerce-documents-create', 'perm': 'commerce',
             'label': T('إنشاء وفتح', 'Create and open'),
             'text': T('ينشئ المستند ويفتحه للتحرير.', 'Creates the document and opens it for editing.'),
             'open_hint': _NEW},
            {'screen': 'commerce.editor', 'target': 'commerce-editor-add-line', 'perm': 'commerce',
             'label': T('اسم الصنف… · الكمية · السعر', 'Item name… · qty · price'),
             'text': T('اكتب الصنف والكمية والسعر الشامل للضريبة، وعلّم «خاضع للضريبة» لو عليه 14%، وEnter أو «إضافة».',
                       'Type the item, quantity and VAT-inclusive price, tick "taxable" for 14% items, then Enter or "Add".'),
             'open_hint': _LINES},
            {'screen': 'commerce.editor', 'target': 'commerce-editor-totals', 'perm': 'commerce',
             'label': T('الإجماليات', 'Totals'),
             'text': T('راجع قبل الضريبة والضريبة والشامل — بيتحسبوا لوحدهم.', 'Check before VAT, VAT and inclusive — they are computed for you.'),
             'open_hint': _LINES},
            {'screen': 'commerce.editor', 'target': 'commerce-editor-export', 'perm': 'commerce',
             'label': T('⬇ تصدير Excel', '⬇ Export Excel'),
             'text': T('ينزّل المستند ملف Excel باسم رقمه تبعته للعميل.', 'Downloads the document as an Excel file named after its number, to send to the client.'),
             'open_hint': _DOC},
         ]},
        {'key': 'hospital_grid', 'shell': 'desktop',
         'title': T('شبكة توزيع لمستشفى متعدد الفروع', 'An allocation grid for a multi-branch hospital'),
         'summary': T('مستند بجهة لها فروع: أصناف بسعر موحّد وكمية لكل فرع.', 'A document for a client with branches: items at one price and a quantity per branch.'),
         'steps': [
            {'screen': 'commerce.documents', 'target': 'commerce-documents-new', 'perm': 'commerce',
             'label': T('+ مستند جديد', '+ New document'),
             'text': T('اختار نوع شبكة التوزيع.', 'Choose the allocation-grid type.')},
            {'screen': 'commerce.documents', 'target': 'commerce-documents-new-recipient', 'perm': 'commerce',
             'label': T('+ جهة جديدة (مستشفى)…', '+ New client (hospital)…'),
             'text': T('الشبكة لازم لها جهة. ضيف المستشفى لو مش موجود.', 'The grid needs a client. Add the hospital if it is not there.'),
             'open_hint': _NEW},
            {'screen': 'commerce.editor', 'target': 'commerce-editor-grid-branches', 'perm': 'commerce',
             'label': T('+ فرع جديد · إضافة فرع', '+ New branch · Add branch'),
             'text': T('ضيف فروع الجهة — كل فرع بيبقى عمود.', 'Add the client\'s branches — each becomes a column.'),
             'open_hint': _GRID},
            {'screen': 'commerce.editor', 'target': 'commerce-editor-grid', 'perm': 'commerce',
             'label': T('الصنف × الفروع', 'Item × branches'),
             'text': T('ضيف الصنف بسعره، واكتب كمية كل فرع في خانته. الإجمالي والقيمة بيتحسبوا لوحدهم.',
                       'Add the item with its price and type each branch\'s quantity in its cell. Totals are computed for you.'),
             'open_hint': _GRID},
            {'screen': 'commerce.editor', 'target': 'commerce-editor-export', 'perm': 'commerce',
             'label': T('⬇ تصدير Excel', '⬇ Export Excel'),
             'text': T('صدّر الشبكة Excel للمستشفى.', 'Export the grid to Excel for the hospital.'),
             'open_hint': _DOC},
         ]},
    ],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول المستندات التجارية', 'A tour of the commercial documents module'),
            'summary': T('إزاي تعمل عرض سعر أو فاتورة بيع أو شبكة توزيع لمستشفى: تنشئ المستند، تضيف البنود بأسعار شاملة الضريبة، وتصدّره Excel. الموديول ده ما بيكتبش في SOFTECH.',
                         'How to make a quotation, sales invoice or hospital allocation grid: create the document, add lines at VAT-inclusive prices, and export it to Excel. This module does not write to SOFTECH.'),
            'roles': ['admin', 'purchasing'],
            'steps': [
                {'target': 'nav-commerce', 'nav': '/commerce',
                 'text': T('«المالية» ← «المستندات التجارية».', '"Finance" → "Commercial documents".'),
                 'more': T('للمستندات اللي بتطلع برّه نقطة البيع: عرض سعر لجهة، فاتورة بيع، أو شبكة توزيع لمستشفى ليها كذا فرع.\n'
                           '• المستندات دي مستقلة — مش بتتسجّل في SOFTECH ولا بتخصم من المخزون.',
                           'For documents issued outside the POS: a quotation for a client, a sales invoice, or an allocation grid for a multi-branch hospital.\n'
                           '• These documents stand alone — they are not posted to SOFTECH and do not deduct stock.')},
                {'target': 'commerce-documents-new', 'route': '/commerce',
                 'text': T('«+ مستند جديد»: النوع والجهة والتاريخ.', '"+ New document": type, client and date.'),
                 'more': T('«النوع» مطلوب، و«الجهة» اختيارية — ولو الجهة جديدة اكتبها في «+ جهة جديدة (مستشفى)…» واضغط «إضافة».\n'
                           '• «إنشاء وفتح» بيعمل المستند ويفتحه على طول لإضافة البنود.',
                           '"Type" is required and "Client" is optional — for a new client type it in "+ New client (hospital)…" and press "Add".\n'
                           '• "Create and open" makes the document and opens it straight away to add lines.')},
                {'target': 'commerce-documents-table', 'route': '/commerce',
                 'text': T('كل المستندات: الرقم، النوع، الجهة، التاريخ، الحالة، البنود، والإجمالي.', 'All documents: number, type, client, date, status, lines and total.'),
                 'more': T('دي قائمة كل المستندات اللي اتعملت، الأحدث تاريخاً فوق.\n'
                           '• ارجع هنا لأي مستند قديم عشان تفتحه وتراجعه أو تكمّل عليه.\n'
                           '• عمود «الحالة» بيوضح حالة كل مستند (زي «draft» للمسودة).',
                           'This is the list of every document created, newest date first.\n'
                           '• Come back here to open any earlier document, review it or carry on with it.\n'
                           '• The "Status" column shows each document\'s status (e.g. "draft").')},
                {'target': 'commerce-documents-table', 'route': '/commerce', 'wait': '/commerce/documents/:id',
                 'text': T('افتح أي مستند — الجولة هتكمّل جوّاه. لو القائمة فاضية اضغط «إنهاء».',
                           'Open any document — the tour continues inside it. If the list is empty, press "End".'),
                 'more': T('اضغط على أي صف (أو «فتح ←») يفتح محرر المستند، والجولة هتكمّل هناك لوحدها.\n'
                           '• لو لسه مفيش مستندات، ابدأ واحد جديد الأول وبعدين ارجع للجولة.',
                           'Click any row (or "Open ←") to open the document editor; the tour carries on there by itself.\n'
                           '• If there are no documents yet, start a new one first and then come back to the tour.')},
                {'target': 'commerce-editor-header', 'route': '/commerce/documents/:id',
                 'text': T('نوع المستند ورقمه والجهة والتاريخ ونسبة الضريبة.', 'The document type and number, client, date and VAT rate.'),
                 'more': T('لو المستند «شبكة توزيع» هتلاقي جدول فيه الأصناف صفوف وفروع الجهة أعمدة، وكل خلية كمية الفرع.\n'
                           '• باقي الأنواع ليها محرر بنود عادي.',
                           'For an "allocation grid" you get a table with items as rows and the client\'s branches as columns, each cell being that branch\'s quantity.\n'
                           '• Other types have a normal line editor.')},
                {'target': 'commerce-editor-add-line', 'route': '/commerce/documents/:id',
                 'text': T('أضف بند: اسم الصنف، الكمية، السعر الشامل، وخاضع للضريبة.', 'Add a line: item name, quantity, inclusive price and taxable.'),
                 'more': T('السعر اللي بتكتبه شامل الضريبة؛ لو علّمت «خاضع للضريبة» النظام بيطلّع جزء الـ14% منه — مش بيزوده فوق السعر.\n'
                           '• «إضافة» أو Enter في خانة الصنف.',
                           'The price you enter includes VAT; if you tick "Taxable" the system extracts the 14% portion from it — it does not add it on top.\n'
                           '• "Add" or Enter in the item box.')},
                {'target': 'commerce-editor-totals', 'route': '/commerce/documents/:id',
                 'text': T('الإجماليات: قبل الضريبة، الضريبة، وشامل الضريبة.', 'Totals: before VAT, VAT and including VAT.'),
                 'more': T('بتتحسب أوتوماتيك من البنود — مش بتتكتب بالإيد.\n'
                           '• راجعها قبل ما تبعت المستند للجهة.',
                           'They are calculated from the lines — never typed by hand.\n'
                           '• Check them before sending the document to the client.')},
                {'target': 'commerce-editor-export', 'route': '/commerce/documents/:id',
                 'text': T('«⬇ تصدير Excel» لتنزيل المستند.', '"⬇ Export Excel" to download the document.'),
                 'more': T('بينزّل ملف Excel باسم رقم المستند، جاهز تبعته للجهة أو تطبعه.',
                           'Downloads an Excel file named after the document number, ready to send to the client or print.')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'commerce.documents',
        'routes': ['/commerce'],
        'title': T('المستندات التجارية', 'Commercial documents'),
        'summary': T('قائمة المستندات (عروض أسعار، فواتير بيع، شبكات توزيع المستشفيات) بالنوع والجهة والتاريخ والحالة والبنود والإجمالي، وإنشاء مستند جديد.', 'The document list (quotations, sales invoices, hospital allocation grids) with type, client, date, status, lines and total, and creating a new document.'),
        'audience': T('المدير والمشتريات.', 'Admins and purchasing.'),
        'steps': [
            T('«مستند جديد»: اختر النوع، والجهة (أو «جهة جديدة» مثل مستشفى)، والتاريخ ← «إنشاء وفتح».', '"New document": choose the type, the client (or "new client" such as a hospital) and the date → "Create and open".'),
        ],
        'tips': [T('لو ظهر «وحدة المستندات التجارية غير مُفعَّلة» يجب تفعيلها من إعدادات السيرفر.', 'If "commercial documents module is not enabled" shows, it must be enabled in the server settings.')],
        'related': ['commerce.editor'],
        'tour': [
            {'target': 'commerce-documents-header', 'text': T('عروض الأسعار وفواتير البيع وشبكات توزيع المستشفيات — لا تكتب في SOFTECH.',
                                              'Quotations, sales invoices and hospital allocation grids — nothing is written to SOFTECH.'),
             'more': T('للمستندات اللي بتطلع لجهات برّه نقطة البيع، زي عرض سعر لمستشفى.\n'
                       '• المستند هنا مش بيخصم من المخزون ولا بيتسجّل في SOFTECH — هو ملف تبعته للجهة.',
                       'For documents issued to clients outside the POS, like a quotation for a hospital.\n'
                       '• A document here does not deduct stock or post to SOFTECH — it is a file you send to the client.')},
            {'target': 'commerce-documents-new', 'text': T('«+ مستند جديد»: اختر النوع والجهة والتاريخ ثم «إنشاء وفتح».',
                                              '"+ New document": pick the type, client and date, then "Create and open".'),
             'more': T('• «النوع» مطلوب، و«الجهة» اختيارية.\n'
                       '• جهة جديدة؟ اكتبها في «+ جهة جديدة (مستشفى)…» واضغط «إضافة».\n'
                       '• «إنشاء وفتح» بيفتح المستند على طول عشان تضيف البنود.',
                       '• "Type" is required and "Client" is optional.\n'
                       '• New client? Type it in "+ New client (hospital)…" and press "Add".\n'
                       '• "Create and open" opens the document right away so you can add lines.'),
             'label': T('+ مستند جديد', '+ New document'),
             'when': T('لعرض أسعار أو فاتورة بيع أو شبكة توزيع لجهة.', 'For a quotation, a sales invoice or an allocation grid for a client.')},
            {'target': 'commerce-documents-table', 'text': T('المستندات بالرقم والنوع والجهة والتاريخ والحالة وعدد البنود والإجمالي.',
                                              'The documents with number, type, client, date, status, line count and total.'),
             'more': T('كل المستندات اللي اتعملت قبل كده.\n'
                       '• لو فاضية هتلاقي «لا توجد مستندات — أنشئ أول مستند».',
                       'Every document made so far.\n'
                       '• When empty it shows "No documents — create the first one".'),
             'label': T('جدول المستندات', 'Documents table'),
             'when': T('ارجع لمستند قديم تعدّله أو تصدّره تاني.', 'Go back to an old document to edit or export it again.')},
            {'target': 'commerce-documents-type', 'label': T('النوع *', 'Type *'),
             'text': T('نوع المستند — الوحيد المطلوب.', 'The document type — the only required field.'),
             'when': T('شبكة التوزيع محتاجة جهة كمان.', 'An allocation grid also needs a client.'),
             'open_hint': _NEW},
            {'target': 'commerce-documents-recipient', 'label': T('الجهة (اختياري)', 'Client (optional)'),
             'text': T('العميل أو الجهة اللي المستند باسمها، أو «— بدون —».', 'The customer or client the document is for, or "— none —".'),
             'open_hint': _NEW},
            {'target': 'commerce-documents-new-recipient', 'label': T('+ جهة جديدة (مستشفى)… · إضافة', '+ New client (hospital)… · Add'),
             'text': T('يضيف جهة جديدة ويختارها على طول.', 'Adds a new client and selects it straight away.'),
             'warn': T('دوّر في القائمة الأول — ماتعملش نفس المستشفى مرتين.', 'Check the list first — do not add the same hospital twice.'),
             'open_hint': _NEW},
            {'target': 'commerce-documents-create', 'label': T('إنشاء وفتح', 'Create and open'),
             'text': T('ينشئ المستند برقم جديد ويفتح صفحة تحريره.', 'Creates the document with a new number and opens its editor.'),
             'open_hint': _NEW},
            {'target': 'commerce-documents-row', 'text': T('اضغط أي صف لفتح المستند وتحرير بنوده؛ يظهر عند وجود مستندات.',
                                              'Click any row to open the document and edit its lines; shown when documents exist.'),
             'more': T('الصف كله قابل للضغط (أو «فتح ←») ويفتح محرر المستند.\n'
                       '• من هناك تعدّل البنود وتصدّر Excel.',
                       'The whole row is clickable (or "Open ←") and opens the document editor.\n'
                       '• From there you edit lines and export to Excel.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-30',
    },
    {
        'key': 'commerce.editor',
        'routes': ['/commerce/documents/:id'],
        'title': T('تحرير المستند التجاري', 'Edit a commercial document'),
        'summary': T('إضافة البنود (اسم الصنف، الكمية، سعر الوحدة شامل الضريبة، خاضع للضريبة أم لا) مع إجماليات حية: قبل الضريبة، الضريبة، وشامل الضريبة. في «شبكة التوزيع»: الصفوف أصناف بسعر موحّد والأعمدة فروع الجهة، وكل خلية كمية الفرع.',
                     'Add lines (item name, quantity, unit price including VAT, taxable or not) with live totals: before VAT, VAT and including VAT. In an "allocation grid": rows are items at one price and columns are the client\'s branches, each cell is that branch\'s quantity.'),
        'audience': T('المدير والمشتريات.', 'Admins and purchasing.'),
        'steps': [T('أضف البنود ثم «تصدير Excel».', 'Add the lines, then "Export Excel".')],
        'tips': [T('الضريبة لا تُضاف فوق السعر؛ السعر المكتوب شامل، ويُستخرج منه جزء 14% للأصناف المعلَّمة.', 'VAT is not added on top; the entered price already includes it, and the 14% portion is extracted for flagged items.')],
        'related': ['commerce.documents'],
        'tour': [
            {'target': 'commerce-editor-header', 'text': T('نوع المستند ورقمه والجهة والتاريخ ونسبة ضريبة القيمة المضافة.',
                                              'The document type and number, client, date and VAT rate.'),
             'more': T('اتأكد إنك على المستند الصح قبل ما تعدّل.\n'
                       '• «← المستندات التجارية» فوق بيرجّعك للقائمة.\n'
                       '• «شبكة التوزيع» بتظهر جدول فروع بدل محرر البنود.',
                       'Make sure you are on the right document before editing.\n'
                       '• "← Commercial documents" at the top returns to the list.\n'
                       '• An "allocation grid" shows a branch table instead of the line editor.')},
            {'target': 'commerce-editor-export', 'text': T('«⬇ تصدير Excel» ينزّل المستند كملف Excel.',
                                              '"⬇ Export Excel" downloads the document as an Excel file.'),
             'more': T('الملف بيتسمّى برقم المستند وفيه البنود والإجماليات.\n'
                       '• صدّر بعد ما تخلص كل البنود؛ لو عدّلت بعدها صدّر تاني.',
                       'The file is named after the document number and holds the lines and totals.\n'
                       '• Export after finishing all lines; if you edit afterwards, export again.'),
             'label': T('⬇ تصدير Excel', '⬇ Export Excel'),
             'when': T('بعد ما تراجع الإجماليات. مفيش حاجة بتتكتب في SOFTECH.', 'After checking the totals. Nothing is written to SOFTECH.')},
            {'target': 'commerce-editor-totals', 'text': T('الإجمالي قبل الضريبة والضريبة والإجمالي شامل الضريبة، يتحدث مع كل بند (لغير شبكات التوزيع).',
                                              'Totals before VAT, VAT and including VAT, updated per line (not for allocation grids).'),
             'more': T('بتتحسب أوتوماتيك من البنود.\n'
                       '• «إجمالى الضريبة» = جزء الـ14% المستخرج من أسعار البنود المعلَّمة «خاضع للضريبة» بس.',
                       'Calculated automatically from the lines.\n'
                       '• "VAT total" = the 14% portion extracted from the prices of lines ticked "Taxable" only.'),
             'label': T('قبل الضريبة · الضريبة · شامل الضريبة', 'Before VAT · VAT · Including VAT'),
             'open_hint': _LINES},
            {'target': 'commerce-editor-lines', 'text': T('البنود: عدّل الصنف أو الكمية أو السعر الشامل مباشرة، و«حذف» لإزالة بند.',
                                              'The lines: edit item, quantity or inclusive price in place; "Delete" removes a line.'),
             'more': T('التعديل بيتحفظ لما تخرج من الخانة، والإجماليات بتتحدّث.\n'
                       '• علامة «خاضع للضريبة» بتتحفظ على طول.\n'
                       '• «حذف» بيطلب تأكيد.',
                       'An edit saves when you leave the box, and the totals update.\n'
                       '• The "Taxable" tick saves straight away.\n'
                       '• "Delete" asks for confirmation.'),
             'label': T('جدول البنود', 'Lines table'),
             'open_hint': _LINES},
            {'target': 'commerce-editor-vat', 'label': T('خاضع للضريبة', 'Taxable'),
             'text': T('علّمه للأصناف اللي عليها ضريبة: 14% بتتحسب من جوه السعر، مش فوقه.', 'Tick it for taxed items: 14% is extracted from the price, not added on top.'),
             'warn': T('علامة غلط بتغيّر الضريبة المكتوبة في المستند — راجعها صنف صنف.', 'A wrong tick changes the VAT on the document — check it item by item.'),
             'open_hint': _LINES},
            {'target': 'commerce-editor-add-line', 'text': T('صف الإضافة: اسم الصنف والكمية والسعر وخاضع للضريبة ثم «إضافة».',
                                              'The add row: item name, quantity, price and taxable flag, then "Add".'),
             'more': T('اكتب السعر شامل الضريبة؛ لو علّمت «خاضع للضريبة» الـ14% بتتحسب من جوه السعر — مش بتتزود فوقه.\n'
                       '• «إضافة» (أو Enter في خانة الصنف) بيشتغل لما تكتب اسم الصنف.',
                       'Enter the VAT-inclusive price; if you tick "Taxable" the 14% is calculated inside the price — not added on top.\n'
                       '• "Add" (or Enter in the item box) works once an item name is typed.'),
             'label': T('اسم الصنف… · الكمية · السعر', 'Item name… · qty · price'),
             'when': T('Enter في خانة الصنف بيضيف على طول.', 'Enter in the item box adds it straight away.'),
             'open_hint': _LINES},
            {'target': 'commerce-editor-add', 'label': T('إضافة', 'Add'),
             'text': T('يضيف البند والإجماليات تتحدث.', 'Adds the line and the totals update.'),
             'open_hint': _LINES},
            {'target': 'commerce-editor-delete-line', 'label': T('حذف', 'Delete'),
             'text': T('يمسح البند بعد تأكيد «حذف البند؟».', 'Removes the line after confirming "Delete the line?".'),
             'warn': T('المسح نهائي — هتضيف البند تاني لو احتجته.', 'Deleting is final — you will re-add the line if needed.'),
             'open_hint': _LINES},
            {'target': 'commerce-editor-grid-branches', 'label': T('+ فرع جديد · إضافة فرع', '+ New branch · Add branch'),
             'text': T('فروع الجهة. كل فرع بيضيف عمود كميات في الشبكة.', 'The client\'s branches. Each branch adds a quantity column to the grid.'),
             'open_hint': _GRID},
            {'target': 'commerce-editor-grid', 'label': T('الصنف × الفروع', 'Item × branches'),
             'text': T('كل صف صنف بسعر موحّد، وكل خلية كمية فرع. إجمالي الكمية والقيمة بيتحسبوا لوحدهم.',
                       'Each row is an item at one price; each cell is a branch quantity. Total quantity and value are computed for you.'),
             'when': T('الكمية بتتحفظ لما تخرج من الخلية.', 'A quantity saves when you leave the cell.'),
             'open_hint': _GRID},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-30',
    },
]
