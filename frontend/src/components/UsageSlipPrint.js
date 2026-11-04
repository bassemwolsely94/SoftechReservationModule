/**
 * components/UsageSlipPrint.js — prints the usage-instructions slip on the 80 mm receipt printer.
 *
 * Same approach as ReceiptPrint.jsx: a small window with an embedded stylesheet, window.print().
 * The content comes from the server (POST /usage-print/sheets/<id>/print/ → slip) — only lines a
 * person confirmed are in it. layout 'per_item' puts every item on its own cut piece.
 */

const esc = (v) => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const CSS = `
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Cairo', 'Arial', sans-serif; direction: rtl; color: #000; background: #fff;
         width: 80mm; max-width: 80mm; padding: 3mm 3mm 6mm; font-size: 12px; }
  .head { text-align: center; margin-bottom: 4px; }
  .pharmacy { font-size: 15px; font-weight: 800; }
  .branch { font-size: 11px; }
  .meta { display: flex; justify-content: space-between; font-size: 11px; border-bottom: 1px dashed #000;
          padding-bottom: 3px; margin-bottom: 4px; }
  .patient { font-size: 12px; font-weight: 700; margin-bottom: 4px; }
  .item { padding: 5px 0; border-bottom: 1px dashed #000; }
  .name { font-size: 13px; font-weight: 800; direction: ltr; text-align: right; }
  .text { font-size: 15px; font-weight: 700; line-height: 1.5; margin-top: 2px; }
  .foot { text-align: center; font-size: 11px; margin-top: 5px; }
  .foot img { width: 26mm; height: 26mm; display: block; margin: 3px auto 0; }
  .piece { page-break-after: always; break-after: page; }
  .piece:last-child { page-break-after: auto; break-after: auto; }
  @page { size: 80mm auto; margin: 0; }
`

function header(s) {
  return `<div class="head"><div class="pharmacy">${esc(s.pharmacy)}</div>
    ${s.branch ? `<div class="branch">${esc(s.branch)}</div>` : ''}</div>
    <div class="meta"><span>فاتورة ${esc(s.invoice)}</span><span>${esc(s.date)}</span></div>
    ${s.patient_name ? `<div class="patient">${esc(s.patient_name)}</div>` : ''}`
}

function footer(s) {
  return (s.footer_blocks || []).map(b => {
    if (b.type === 'qr') {
      return `<div class="foot"><img src="${esc(b.image)}" alt="">${b.caption ? `<div>${esc(b.caption)}</div>` : ''}</div>`
    }
    return `<div class="foot">${esc(b.text)}</div>`
  }).join('')
}

const itemHtml = (it) => `<div class="item"><div class="name">${esc(it.name)}</div><div class="text">${esc(it.text)}</div></div>`

export function slipHtml(s) {
  const body = s.layout === 'per_item'
    ? s.items.map(it => `<div class="piece">${header(s)}${itemHtml(it)}${footer(s)}</div>`).join('')
    : `${header(s)}${s.items.map(itemHtml).join('')}${footer(s)}`
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
    <title>طريقة الاستخدام ${esc(s.invoice)}</title><style>${CSS}</style></head><body>${body}</body></html>`
}

/** Returns false when the browser blocked the print window. */
export function printUsageSlip(slip) {
  const w = window.open('', '_blank', 'width=420,height=700')
  if (!w) return false
  w.document.open()
  w.document.write(slipHtml(slip))
  w.document.close()
  w.focus()
  const go = () => { w.print(); setTimeout(() => w.close(), 300) }
  const imgs = Array.from(w.document.images)
  if (imgs.length) Promise.all(imgs.map(i => i.complete ? null : new Promise(r => { i.onload = i.onerror = r }))).then(go)
  else setTimeout(go, 50)
  return true
}
