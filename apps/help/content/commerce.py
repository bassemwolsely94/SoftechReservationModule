from . import T

MODULE = {
    'key': 'commerce', 'group': 'finance', 'icon': '🧩',
    'title': T('المستندات التجارية', 'Commercial documents'),
    'summary': T(
        'إصدار مستندات تجارية خارج نقطة البيع: عروض أسعار، فواتير بيع لعميل تجزئة/توصيل، و«شبكات توزيع» للمستشفيات والجهات متعددة الفروع '
        '(صنف بسعر موحّد وكمية لكل فرع من فروع الجهة). الأسعار شاملة الضريبة، ويُحسب جزء ضريبة 14% تلقائياً للأصناف الخاضعة. التصدير Excel. لا يكتب في SOFTECH.',
        'Issue commercial documents outside the POS: quotations, sales invoices for a retail/delivery customer, and "allocation grids" for hospitals and multi-branch clients '
        '(an item at one unit price with a quantity per client branch). Prices include VAT; the 14% VAT portion is calculated automatically for taxable items. Export to Excel. Nothing is written to SOFTECH.'),
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
        'tips': [T('لو ظهر «وحدة المستندات التجارية غير مُفعَّلة» يجب تفعيلها من إعدادات الخادم.', 'If "commercial documents module is not enabled" shows, it must be enabled in the server settings.')],
        'related': ['commerce.editor'],
        'tour': [
            {'target': 'commerce-documents-header', 'text': T('عروض الأسعار وفواتير البيع وشبكات توزيع المستشفيات — لا تكتب في SOFTECH.',
                                              'Quotations, sales invoices and hospital allocation grids — nothing is written to SOFTECH.')},
            {'target': 'commerce-documents-new', 'text': T('«+ مستند جديد»: اختر النوع والجهة والتاريخ ثم «إنشاء وفتح».',
                                              '"+ New document": pick the type, client and date, then "Create and open".')},
            {'target': 'commerce-documents-table', 'text': T('المستندات بالرقم والنوع والجهة والتاريخ والحالة وعدد البنود والإجمالي.',
                                              'The documents with number, type, client, date, status, line count and total.')},
            {'target': 'commerce-documents-row', 'text': T('اضغط أي صف لفتح المستند وتحرير بنوده؛ يظهر عند وجود مستندات.',
                                              'Click any row to open the document and edit its lines; shown when documents exist.')},
        ],
        'updated': '2026-10-11',
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
                                              'The document type and number, client, date and VAT rate.')},
            {'target': 'commerce-editor-export', 'text': T('«⬇ تصدير Excel» ينزّل المستند كملف Excel.',
                                              '"⬇ Export Excel" downloads the document as an Excel file.')},
            {'target': 'commerce-editor-totals', 'text': T('الإجمالي قبل الضريبة والضريبة والإجمالي شامل الضريبة، يتحدث مع كل بند (لغير شبكات التوزيع).',
                                              'Totals before VAT, VAT and including VAT, updated per line (not for allocation grids).')},
            {'target': 'commerce-editor-lines', 'text': T('البنود: عدّل الصنف أو الكمية أو السعر الشامل مباشرة، و«حذف» لإزالة بند.',
                                              'The lines: edit item, quantity or inclusive price in place; "Delete" removes a line.')},
            {'target': 'commerce-editor-add-line', 'text': T('صف الإضافة: اسم الصنف والكمية والسعر وخاضع للضريبة ثم «إضافة».',
                                              'The add row: item name, quantity, price and taxable flag, then "Add".')},
        ],
        'updated': '2026-10-11',
    },
]
