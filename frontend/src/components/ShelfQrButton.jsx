/**
 * ShelfQrButton.jsx
 * Staff tool: generate a printable shelf QR for an item at a branch. The QR opens
 * the public /notify page so a customer can register interest when it's out of stock.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { demandApi, branchesApi } from '../api/client'

export default function ShelfQrButton({ productId, productName = '' }) {
  const [open, setOpen]     = useState(false)
  const [branch, setBranch] = useState('')

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
    enabled: open,
  })
  const { data: qr } = useQuery({
    queryKey: ['shelf-qr', productId, branch],
    queryFn: () => demandApi.shelfQr({ item: productId, branch }).then(r => r.data),
    enabled: open && !!branch,
  })

  function printLabel() {
    if (!qr?.qr_code) return
    // Resolve the live brand color — the print window has no stylesheet/CSS vars
    const navyRgb = getComputedStyle(document.documentElement)
      .getPropertyValue('--c-brand-600').trim() || '2 40 113'
    const navy = `rgb(${navyRgb})`
    const w = window.open('', '_blank', 'width=400,height=560')
    w.document.write(`<!doctype html><html dir="rtl"><head><meta charset="utf-8"><title>QR</title></head>
      <body style="font-family:sans-serif;text-align:center;padding:24px">
        <div style="font-weight:800;font-size:18px;color:${navy}">صيدليات الرزيقي</div>
        <div style="font-size:13px;color:#555;margin:6px 0 16px">غير متوفر؟ امسح الكود ليصلك إشعار عند توفره</div>
        <img src="data:image/png;base64,${qr.qr_code}" style="width:260px;height:260px"/>
        <div style="font-weight:700;margin-top:14px">${(productName || '').replace(/</g, '')}</div>
      </body></html>`)
    w.document.close(); w.focus(); setTimeout(() => w.print(), 300)
  }

  return (
    <>
      <button onClick={() => setOpen(true)} className="btn-secondary text-sm">🔳 QR للرف</button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setOpen(false)} />
          <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
            <h3 className="font-black text-gray-900 text-base mb-1">🔳 رمز QR للرف</h3>
            <p className="text-xs text-gray-500 mb-4">يفتح صفحة "أبلغني عند توفره" لهذا الصنف في الفرع المختار.</p>
            <label className="block text-xs font-semibold text-gray-600 mb-1">الفرع</label>
            <select className="input-field mb-4" value={branch} onChange={e => setBranch(e.target.value)}>
              <option value="">اختر الفرع...</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
            {branch && qr?.qr_code && (
              <div className="text-center">
                <img alt="QR" src={`data:image/png;base64,${qr.qr_code}`} className="w-48 h-48 mx-auto" />
                <div className="text-[11px] text-gray-400 font-mono mt-2 break-all">{qr.url}</div>
              </div>
            )}
            <div className="flex gap-2 justify-end mt-5">
              <button onClick={() => setOpen(false)} className="btn-secondary text-sm px-4">إغلاق</button>
              <button onClick={printLabel} disabled={!qr?.qr_code}
                className="btn-primary text-sm px-4 disabled:opacity-50">🖨 طباعة الملصق</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
