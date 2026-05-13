/**
 * components/ReceiptPrint.jsx
 *
 * Universal print receipt for reservations and transfers.
 * Uses browser window.print() — no libraries needed.
 * Opens a new window with a styled receipt, prints automatically.
 *
 * Usage:
 *   import { printReservationReceipt, printTransferReceipt } from '../components/ReceiptPrint'
 *   <button onClick={() => printReservationReceipt(reservation)}>طباعة</button>
 */

// ── Status labels ─────────────────────────────────────────────────────────────
const STATUS_AR = {
  pending:     'قيد الانتظار',
  available:   'المخزون متاح',
  contacted:   'تم التواصل',
  confirmed:   'مؤكد',
  fulfilled:   'تم التسليم',
  cancelled:   'ملغي',
  expired:     'منتهي',
  draft:       'مسودة',
  submitted:   'مُقدَّم',
  approved:    'معتمد',
  rejected:    'مرفوض',
  sent_to_erp: 'أُرسل للـ ERP',
  completed:   'مكتمل',
}

const PRIORITY_AR = {
  normal:  'عادي',
  urgent:  'عاجل 🚨',
  chronic: 'مريض مزمن 💊',
}

// ── Date formatter ────────────────────────────────────────────────────────────
function fmtDate(d) {
  if (!d) return '—'
  try {
    return new Date(d).toLocaleDateString('ar-EG', {
      day: 'numeric', month: 'long', year: 'numeric',
    })
  } catch { return d }
}

function fmtDateTime(d) {
  if (!d) return '—'
  try {
    return new Date(d).toLocaleString('ar-EG', {
      day: 'numeric', month: 'long', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return d }
}

// ── Receipt CSS (embedded, no external dependencies) ─────────────────────────
const RECEIPT_CSS = `
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Cairo', 'Arial', sans-serif;
    direction: rtl;
    font-size: 12px;
    color: #111;
    background: white;
    padding: 8px;
    width: 80mm;          /* 80mm thermal receipt width */
    max-width: 80mm;
  }

  /* For A4 printing — override width */
  body.a4 {
    width: 100%;
    max-width: 100%;
    padding: 20px 30px;
    font-size: 13px;
  }

  .logo-area {
    text-align: center;
    border-bottom: 1px dashed #888;
    padding-bottom: 8px;
    margin-bottom: 8px;
  }
  .pharmacy-name {
    font-size: 16px;
    font-weight: 900;
    letter-spacing: 0.5px;
  }
  .pharmacy-sub {
    font-size: 10px;
    color: #555;
    margin-top: 2px;
  }

  .receipt-type {
    text-align: center;
    font-size: 13px;
    font-weight: 700;
    margin: 6px 0 4px;
    padding: 4px;
    border: 1px solid #222;
    border-radius: 4px;
  }

  .status-badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 20px;
    border: 1px solid currentColor;
    margin: 4px auto;
  }

  .ref-number {
    text-align: center;
    font-size: 11px;
    color: #555;
    margin-bottom: 8px;
    font-family: monospace;
  }

  .divider {
    border: none;
    border-top: 1px dashed #888;
    margin: 6px 0;
  }
  .divider-solid {
    border: none;
    border-top: 2px solid #222;
    margin: 6px 0;
  }

  .section-title {
    font-size: 10px;
    font-weight: 700;
    color: #555;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
  }

  .row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 3px;
  }
  .row-label {
    color: #555;
    font-size: 11px;
    flex-shrink: 0;
    min-width: 35%;
  }
  .row-value {
    font-weight: 600;
    font-size: 11px;
    text-align: left;
    word-break: break-word;
  }
  .row-value.ltr { direction: ltr; text-align: right; }

  .item-box {
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 6px 8px;
    margin: 6px 0;
  }
  .item-name {
    font-size: 13px;
    font-weight: 800;
  }
  .item-sub {
    font-size: 10px;
    color: #666;
    margin-top: 2px;
    font-style: italic;
  }
  .item-qty {
    font-size: 12px;
    font-weight: 700;
    margin-top: 4px;
  }

  .note-box {
    border: 1px dashed #aaa;
    border-radius: 3px;
    padding: 5px 8px;
    font-size: 11px;
    color: #333;
    margin: 6px 0;
    line-height: 1.5;
  }

  .footer {
    text-align: center;
    font-size: 10px;
    color: #777;
    margin-top: 10px;
    border-top: 1px dashed #888;
    padding-top: 6px;
    line-height: 1.7;
  }

  .urgent-banner {
    background: #111;
    color: white;
    text-align: center;
    font-size: 12px;
    font-weight: 800;
    padding: 4px;
    border-radius: 3px;
    margin: 4px 0;
    letter-spacing: 1px;
  }

  .barcode-area {
    text-align: center;
    margin: 6px 0;
    font-family: monospace;
    font-size: 10px;
    letter-spacing: 2px;
    color: #555;
  }

  @media print {
    body { padding: 0; }
    @page { margin: 4mm; size: 80mm auto; }
    body.a4 { @page { size: A4; margin: 15mm; } }
  }
`

// ── HTML builder ──────────────────────────────────────────────────────────────

function buildReservationHTML(r) {
  const status    = STATUS_AR[r.status] || r.status
  const priority  = PRIORITY_AR[r.priority] || r.priority
  const isUrgent  = r.priority === 'urgent'
  const isChronic = r.priority === 'chronic'

  // Status → receipt title
  const RECEIPT_TITLES = {
    pending:   'إشعار حجز — قيد الانتظار',
    available: 'إشعار حجز — المخزون متاح',
    contacted: 'إشعار حجز — تم التواصل',
    confirmed: 'تأكيد حجز',
    fulfilled: 'إيصال تسليم',
    cancelled: 'إشعار إلغاء حجز',
    expired:   'إشعار انتهاء حجز',
  }
  const title = RECEIPT_TITLES[r.status] || 'إشعار حجز'

  const rows = [
    ['العميل',     r.contact_name || r.customer_name || '—'],
    ['الهاتف',     r.contact_phone || r.customer_phone || '—', true],
    ['الفرع',      r.branch_name || '—'],
    ['مسؤول',      r.assigned_to_name || '—'],
    ['التاريخ',    fmtDateTime(r.created_at)],
  ]

  if (r.expected_arrival_date) {
    rows.push(['وصول متوقع', fmtDate(r.expected_arrival_date)])
  }
  if (r.follow_up_date) {
    rows.push(['تاريخ المتابعة', fmtDate(r.follow_up_date)])
  }
  if (r.fulfilled && r.updated_at) {
    rows.push(['تاريخ التسليم', fmtDateTime(r.updated_at)])
  }
  if (r.sales_transaction_id) {
    rows.push(['رقم معاملة ERP', r.sales_transaction_id, true])
  }

  return `<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>${title} #${r.id}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>${RECEIPT_CSS}</style>
</head>
<body>
  <!-- Header -->
  <div class="logo-area">
    <div class="pharmacy-name">صيدليات الرزيقي</div>
    <div class="pharmacy-sub">ElRezeiky Pharmacies — منصة العمليات</div>
  </div>

  <!-- Receipt type -->
  <div class="receipt-type">${title}</div>

  <!-- Status badge -->
  <div style="text-align:center; margin: 4px 0;">
    <span class="status-badge">${status}</span>
  </div>

  <!-- Urgent banner -->
  ${isUrgent  ? '<div class="urgent-banner">🚨 عاجل — يحتاج اهتمام فوري</div>' : ''}
  ${isChronic ? '<div class="urgent-banner">💊 مريض مزمن</div>' : ''}

  <!-- Reference -->
  <div class="ref-number">رقم الحجز: #${r.id}</div>
  <hr class="divider-solid">

  <!-- Item -->
  <div class="section-title">الصنف المطلوب</div>
  <div class="item-box">
    <div class="item-name">${r.item_name || '—'}</div>
    ${r.item_scientific ? `<div class="item-sub">${r.item_scientific}</div>` : ''}
    <div class="item-qty">الكمية: ${r.quantity_requested || 1} وحدة</div>
  </div>

  <hr class="divider">

  <!-- Details -->
  <div class="section-title">تفاصيل العميل والحجز</div>
  ${rows.map(([label, value, ltr]) => `
    <div class="row">
      <span class="row-label">${label}</span>
      <span class="row-value${ltr ? ' ltr' : ''}">${value}</span>
    </div>`).join('')}

  ${r.notes ? `
  <hr class="divider">
  <div class="section-title">ملاحظات</div>
  <div class="note-box">${r.notes}</div>` : ''}

  <!-- Delivery address -->
  ${r.delivery_location_text ? `
  <hr class="divider">
  <div class="section-title">عنوان التوصيل</div>
  <div class="note-box">${r.delivery_location_text}</div>` : ''}

  <!-- Status message per workflow -->
  ${r.status === 'available' ? `
  <hr class="divider">
  <div class="note-box" style="text-align:center; font-weight:700; font-size:12px;">
    ✅ المخزون متاح — يرجى التواصل مع العميل فوراً
  </div>` : ''}

  ${r.status === 'fulfilled' ? `
  <hr class="divider">
  <div class="note-box" style="text-align:center; font-weight:700;">
    ✅ تم التسليم بنجاح
    ${r.is_erp_validated ? '<br>🔗 تم التحقق من الـ ERP' : ''}
  </div>` : ''}

  <!-- Barcode-style ID -->
  <hr class="divider">
  <div class="barcode-area">
    ||||| ${String(r.id).padStart(8, '0')} |||||
  </div>

  <!-- Footer -->
  <div class="footer">
    طُبع بتاريخ: ${fmtDateTime(new Date().toISOString())}<br>
    صيدليات الرزيقي — جميع الحقوق محفوظة
  </div>
</body>
</html>`
}

function buildTransferHTML(t) {
  const status = STATUS_AR[t.status] || t.status

  const RECEIPT_TITLES = {
    draft:       'مسودة طلب تحويل',
    submitted:   'طلب تحويل — مُقدَّم للاعتماد',
    approved:    'موافقة على طلب تحويل',
    rejected:    'رفض طلب تحويل',
    sent_to_erp: 'طلب تحويل — أُرسل للـ ERP',
    completed:   'إتمام تحويل مخزون',
  }
  const title = RECEIPT_TITLES[t.status] || 'إشعار تحويل مخزون'

  const itemsHTML = (t.items || []).map(item => `
    <div class="row" style="border-bottom:1px dotted #ddd; padding-bottom:3px; margin-bottom:3px;">
      <span class="row-label" style="max-width:60%;">${item.item_name || item.item?.name || '—'}</span>
      <span class="row-value">${item.quantity_requested} وحدة</span>
    </div>`).join('')

  return `<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <title>${title} #${t.id}</title>
  <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>${RECEIPT_CSS}</style>
</head>
<body>
  <div class="logo-area">
    <div class="pharmacy-name">صيدليات الرزيقي</div>
    <div class="pharmacy-sub">ElRezeiky Pharmacies — منصة العمليات</div>
  </div>

  <div class="receipt-type">${title}</div>
  <div style="text-align:center; margin: 4px 0;">
    <span class="status-badge">${status}</span>
  </div>
  <div class="ref-number">رقم التحويل: #${t.id} ${t.transfer_number ? `| ${t.transfer_number}` : ''}</div>
  <hr class="divider-solid">

  <!-- Branches -->
  <div class="section-title">الفروع</div>
  <div class="row">
    <span class="row-label">من فرع</span>
    <span class="row-value">${t.requesting_branch_name || '—'}</span>
  </div>
  <div class="row">
    <span class="row-label">إلى فرع</span>
    <span class="row-value">${t.supplying_branch_name || '—'}</span>
  </div>

  <hr class="divider">

  <!-- Items -->
  <div class="section-title">الأصناف (${(t.items || []).length} صنف)</div>
  ${itemsHTML || '<div style="color:#888;font-size:11px;">لا توجد أصناف</div>'}

  <hr class="divider">

  <!-- Details -->
  <div class="section-title">تفاصيل الطلب</div>
  <div class="row">
    <span class="row-label">طلب بواسطة</span>
    <span class="row-value">${t.created_by_name || '—'}</span>
  </div>
  <div class="row">
    <span class="row-label">تاريخ الطلب</span>
    <span class="row-value">${fmtDateTime(t.created_at)}</span>
  </div>
  ${t.approved_by_name ? `
  <div class="row">
    <span class="row-label">اعتمد بواسطة</span>
    <span class="row-value">${t.approved_by_name}</span>
  </div>` : ''}
  ${t.submitted_at ? `
  <div class="row">
    <span class="row-label">تاريخ التقديم</span>
    <span class="row-value">${fmtDateTime(t.submitted_at)}</span>
  </div>` : ''}
  ${t.transfer_transaction_id ? `
  <div class="row">
    <span class="row-label">رقم ERP</span>
    <span class="row-value ltr">${t.transfer_transaction_id}</span>
  </div>` : ''}
  ${t.erp_reference ? `
  <div class="row">
    <span class="row-label">مرجع ERP</span>
    <span class="row-value ltr">${t.erp_reference}</span>
  </div>` : ''}

  ${t.notes ? `
  <hr class="divider">
  <div class="section-title">ملاحظات</div>
  <div class="note-box">${t.notes}</div>` : ''}

  ${t.status === 'approved' ? `
  <hr class="divider">
  <div class="note-box" style="text-align:center;font-weight:700;">
    ✅ تمت الموافقة — يمكن إرسال الطلب للـ ERP
  </div>` : ''}

  ${t.status === 'completed' ? `
  <hr class="divider">
  <div class="note-box" style="text-align:center;font-weight:700;">
    ✅ تم إتمام التحويل بنجاح
    ${t.is_erp_validated ? '<br>🔗 تم التحقق من الـ ERP' : ''}
  </div>` : ''}

  <hr class="divider">
  <div class="barcode-area">||||| ${String(t.id).padStart(8, '0')} |||||</div>

  <div class="footer">
    طُبع بتاريخ: ${fmtDateTime(new Date().toISOString())}<br>
    صيدليات الرزيقي — جميع الحقوق محفوظة
  </div>
</body>
</html>`
}

// ── Print functions ───────────────────────────────────────────────────────────

export function printReservationReceipt(reservation) {
  const html   = buildReservationHTML(reservation)
  const win    = window.open('', '_blank', 'width=400,height=700')
  if (!win) {
    alert('يرجى السماح بالنوافذ المنبثقة لطباعة الإيصال')
    return
  }
  win.document.write(html)
  win.document.close()
  // Wait for fonts to load then print
  win.onload = () => {
    setTimeout(() => {
      win.focus()
      win.print()
    }, 600)
  }
}

export function printTransferReceipt(transfer) {
  const html = buildTransferHTML(transfer)
  const win  = window.open('', '_blank', 'width=400,height=700')
  if (!win) {
    alert('يرجى السماح بالنوافذ المنبثقة لطباعة الإيصال')
    return
  }
  win.document.write(html)
  win.document.close()
  win.onload = () => {
    setTimeout(() => {
      win.focus()
      win.print()
    }, 600)
  }
}

// ── Print Button component ────────────────────────────────────────────────────

export function PrintButton({ onClick, label = '🖨️ طباعة', className = '' }) {
  return (
    <button
      onClick={onClick}
      className={`btn-secondary text-sm flex items-center gap-2 ${className}`}
    >
      🖨️ {label}
    </button>
  )
}
