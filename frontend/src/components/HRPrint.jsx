/**
 * components/HRPrint.jsx
 *
 * Printable A4 slips for HR requests, mirroring the El Rezeiky paper forms
 * (طلب إجازة · اذن مأمورية · تعديل فترة العمل · إضافي · سلفة · مصروفات).
 * Uses browser window.print() — same mechanism as ReceiptPrint.jsx, no libs.
 *
 * Usage:
 *   import { printHRRequest } from '../components/HRPrint'
 *   <button onClick={() => printHRRequest('leave', row)}>طباعة</button>
 */

// ── Formatters ──────────────────────────────────────────────────────────────
function fmtDate(d) {
  if (!d) return '..... / ..... / .....'
  try {
    const dt = new Date(d)
    const day = dt.toLocaleDateString('ar-EG', { weekday: 'long' })
    const date = dt.toLocaleDateString('ar-EG', { day: '2-digit', month: '2-digit', year: 'numeric' })
    return `${day} ${date}`
  } catch { return d }
}
function fmtTime(t) {
  if (!t) return '.....'
  // t is "HH:MM:SS" or "HH:MM"
  const parts = String(t).split(':')
  if (parts.length >= 2) return `${parts[0]}:${parts[1]}`
  return t
}
function esc(s) {
  return String(s ?? '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
}

// ── Shared CSS (A4, RTL, El Rezeiky branding + signature blocks) ──────────────
const HR_CSS = `
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Cairo', 'Arial', sans-serif;
    direction: rtl; color: #111; background: #fff;
    padding: 24px 32px; font-size: 14px; line-height: 1.9;
  }
  .sheet { max-width: 720px; margin: 0 auto; border: 2px solid #111; padding: 22px 26px; }
  .head { display: flex; align-items: center; justify-content: space-between;
          border-bottom: 2px solid #111; padding-bottom: 10px; margin-bottom: 6px; }
  .brand { text-align: right; }
  .brand .ar { font-size: 20px; font-weight: 900; }
  .brand .en { font-size: 11px; color: #555; letter-spacing: 1px; }
  .dept { text-align: left; font-size: 12px; color: #333; font-weight: 700; }
  .title { text-align: center; font-size: 18px; font-weight: 900; margin: 14px 0 4px;
           padding: 6px; border: 1.5px solid #111; border-radius: 6px; }
  .meta { display: flex; justify-content: space-between; font-size: 12px; color: #555; margin: 6px 2px 14px; }
  .field { margin: 6px 0; }
  .field .lbl { font-weight: 700; }
  .field .val { border-bottom: 1px dotted #333; padding: 0 6px; font-weight: 600; min-width: 60px; display: inline-block; }
  .statement { margin: 14px 0; font-size: 15px; line-height: 2.2; }
  .notes { border: 1px dashed #999; border-radius: 4px; padding: 8px 10px; margin: 12px 0; min-height: 40px; }
  .notes .lbl { font-weight: 700; color: #555; font-size: 12px; }
  .status { display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 12px;
            border: 1px solid #111; border-radius: 20px; }
  .signs { display: flex; justify-content: space-between; gap: 18px; margin-top: 40px; }
  .sign { flex: 1; text-align: center; }
  .sign .line { border-top: 1.5px solid #111; margin-bottom: 4px; padding-top: 30px; }
  .sign .cap { font-size: 12px; font-weight: 700; color: #333; }
  .foot { text-align: center; font-size: 10px; color: #888; margin-top: 18px;
          border-top: 1px dashed #aaa; padding-top: 6px; }
  @media print { body { padding: 0; } .sheet { border: none; } @page { size: A4; margin: 14mm; } }
`

const STATUS_AR = {
  draft: 'مسودة', submitted: 'بانتظار الاعتماد', pending: 'بانتظار الاعتماد',
  approved: 'معتمد', rejected: 'مرفوض', paid: 'تم الصرف', settled: 'تمت التسوية', cancelled: 'ملغي',
}

function signBlock(caps) {
  return `<div class="signs">${caps.map(c => `<div class="sign"><div class="line"></div><div class="cap">${c}</div></div>`).join('')}</div>`
}

function field(lbl, val) {
  return `<div class="field"><span class="lbl">${lbl}:</span> <span class="val">${val}</span></div>`
}

// ── Per-type body builders ────────────────────────────────────────────────────
function buildBody(kind, r) {
  const name = esc(r.employee_name || r.staff_name || '—')
  const code = esc(r.employee_hr_code || r.staff_code || '—')
  const status = STATUS_AR[r.status] || esc(r.status || '')
  const approvers = (r.approver_names || []).map(esc).join('، ')
  const onBehalf = r.submitted_by_name && r.submitted_by_name !== (r.staff_name || r.employee_name)

  const extraMeta = [
    onBehalf ? `<div class="field"><span class="lbl">قُدِّم بواسطة:</span> <span class="val">${esc(r.submitted_by_name)}</span></div>` : '',
    approvers ? `<div class="field"><span class="lbl">المعتمِدون المختارون:</span> <span class="val">${approvers}</span></div>` : '',
  ].join('')

  const identity =
    `<div class="meta"><span>كود الموارد البشرية: <b>${code}</b></span><span>الحالة: <span class="status">${status}</span></span></div>` +
    field('الاسم', name) + extraMeta

  if (kind === 'leave') {
    return {
      title: 'طلب إجازة',
      html: identity +
        field('تاريخ الطلب', fmtDate(r.created_at)) +
        `<div class="statement">أرجو الموافقة على منحي إجازة <b>${esc(r.leave_type_name || '')}</b> لمدة <span class="val">${esc(r.days_requested ?? '')}</span> يوم،<br>` +
        `اعتباراً من <span class="val">${fmtDate(r.start_date)}</span> إلى <span class="val">${fmtDate(r.end_date)}</span>،<br>` +
        `على أن أعود للعمل يوم <span class="val">${fmtDate(r.return_to_work_date)}</span>.</div>` +
        `<div class="notes"><span class="lbl">ملاحظات:</span> ${esc(r.reason || '')}</div>`,
      signs: ['توقيع الموظف', 'توقيع الرئيس المباشر', 'توقيع المدير الإداري'],
    }
  }

  if (kind === 'permit' && r.permit_type === 'shift_change') {
    // Mirrors the management "تعديل فترة العمل" notice wording
    return {
      title: 'تعديل فترة العمل',
      html: `<div class="meta"><span>كود الموارد البشرية: <b>${code}</b></span><span>الحالة: <span class="status">${status}</span></span></div>` +
        extraMeta +
        `<div class="statement">تحية طيبة وبعد،<br>نفيد علم سيادتكم بأنه قد تم تعديل فترة عمل السيد/ <b>${name}</b> ` +
        `اعتباراً من يوم <span class="val">${fmtDate(r.date)}</span> ` +
        `من الساعة <span class="val">${fmtTime(r.time_from)}</span> إلى الساعة <span class="val">${fmtTime(r.time_to)}</span>.</div>` +
        `<div class="notes"><span class="lbl">السبب / ملاحظات:</span> ${esc(r.reason || '')}</div>`,
      signs: ['توقيع الرئيس المباشر', 'توقيع المدير الإداري', 'توقيع مدير الفرع'],
    }
  }

  if (kind === 'permit') {
    // اذن مأمورية
    return {
      title: 'اذن مأمورية',
      html: identity +
        field('التاريخ', fmtDate(r.date)) +
        `<div class="statement">مأمورية إلى <span class="val">${esc(r.destination || '')}</span>،<br>` +
        `من الساعة <span class="val">${fmtTime(r.time_from)}</span> حتى الساعة <span class="val">${fmtTime(r.time_to)}</span>.</div>` +
        `<div class="notes"><span class="lbl">السبب:</span> ${esc(r.reason || '')}</div>`,
      signs: ['توقيع الموظف', 'توقيع الرئيس المباشر', 'توقيع المدير الإداري'],
    }
  }

  if (kind === 'overtime') {
    return {
      title: 'طلب عمل إضافي',
      html: identity +
        field('التاريخ', fmtDate(r.date)) +
        `<div class="statement">أرجو احتساب عمل إضافي لعدد <span class="val">${esc(r.hours ?? '')}</span> ساعة.</div>` +
        `<div class="notes"><span class="lbl">السبب:</span> ${esc(r.reason || '')}</div>`,
      signs: ['توقيع الموظف', 'توقيع الرئيس المباشر', 'توقيع المدير الإداري'],
    }
  }

  if (kind === 'advance') {
    return {
      title: 'طلب سلفة',
      html: identity +
        field('تاريخ الطلب', fmtDate(r.created_at)) +
        `<div class="statement">أرجو الموافقة على صرف سلفة بمبلغ <span class="val">${esc(Number(r.amount || 0).toLocaleString('ar-EG'))}</span> جنيه،<br>` +
        `على أن يتم السداد بتاريخ <span class="val">${fmtDate(r.repayment_date)}</span>.</div>` +
        `<div class="notes"><span class="lbl">السبب:</span> ${esc(r.reason || '')}</div>`,
      signs: ['توقيع الموظف', 'توقيع الرئيس المباشر', 'توقيع المدير المالي'],
    }
  }

  if (kind === 'expense') {
    const isMam = r.category === 'mamoriya'
    let extra = ''
    if (isMam) {
      extra = field('وجهة المأمورية', esc(r.trip_destination || '—')) +
        field('من', fmtDate(r.trip_start)) + field('إلى', fmtDate(r.trip_end)) +
        field('بدل المأمورية', `${esc(Number(r.allowance_amount || 0).toLocaleString('ar-EG'))} ج`)
    }
    return {
      title: 'مطالبة مصروفات',
      html: identity +
        field('الفئة', esc(r.category_display || r.category || '')) +
        field('تاريخ المصروف', fmtDate(r.expense_date)) +
        field('المبلغ', `${esc(Number(r.amount || 0).toLocaleString('ar-EG'))} ج`) +
        extra +
        `<div class="notes"><span class="lbl">الوصف:</span> ${esc(r.description || '')}</div>`,
      signs: ['توقيع الموظف', 'توقيع الرئيس المباشر', 'توقيع المدير المالي'],
    }
  }

  return { title: 'طلب', html: identity, signs: ['توقيع الموظف', 'توقيع الرئيس المباشر'] }
}

// ── Public API ────────────────────────────────────────────────────────────────
export function printHRRequest(kind, row) {
  const { title, html, signs } = buildBody(kind, row)
  const doc = `<!DOCTYPE html>
<html lang="ar-u-nu-latn" dir="rtl"><head><meta charset="UTF-8">
<title>${title} #${row.id || ''}</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>${HR_CSS}</style></head>
<body>
  <div class="sheet">
    <div class="head">
      <div class="brand"><div class="ar">صيدليات الرزيقي</div><div class="en">EL REZEIKY PHARMACIES</div></div>
      <div class="dept">إدارة الموارد البشرية<br>إدارة الأفرع</div>
    </div>
    <div class="title">${title}</div>
    ${html}
    ${signBlock(signs)}
    <div class="foot">طُبع بتاريخ: ${new Date().toLocaleString('ar-EG')} — صيدليات الرزيقي</div>
  </div>
</body></html>`

  const win = window.open('', '_blank', 'width=800,height=900')
  if (!win) { alert('يرجى السماح بالنوافذ المنبثقة للطباعة'); return }
  win.document.write(doc)
  win.document.close()
  win.onload = () => { setTimeout(() => { win.focus(); win.print() }, 500) }
}

export function HRPrintButton({ onClick }) {
  return (
    <button onClick={onClick} title="طباعة"
      className="text-xs text-gray-500 hover:text-brand-700 hover:underline">🖨️ طباعة</button>
  )
}
