/**
 * «🛵 طلبات المنصات» — the branch's accepted marketplace orders waiting for the SOFTECH cashier (doc 38).
 * Shown only when there is at least one. Each order keeps the platform's own lines (not edited here);
 * the server prices it, posts it 100% آجل on the platform's account and refuses any cash/card tender.
 * «معاينة» = dry run (nothing written). «إرسال» appears only while the writer switch is on.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../../api/client'
import { confirmBar } from '../../components/ui'

const money = v => (v == null || v === '' ? '—' : Number(v).toFixed(2))
const errText = e => {
  const d = e?.response?.data
  if (d?.errors) return `${d.detail || ''} ${Object.values(d.errors).flat().map(x => (typeof x === 'object' ? JSON.stringify(x) : x)).join(' · ')}`.trim()
  return d?.detail || e?.message || 'خطأ'
}

export default function PlatformDraftsButton({ branch, writerEnabled }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(null)
  const [note, setNote] = useState({})
  const q = useQuery({
    queryKey: ['pos', 'platform-drafts', branch],
    queryFn: () => api.get('/pos-orders/platform-drafts/', { params: { branch } }).then(r => r.data.results || []),
    enabled: !!branch,
    refetchInterval: 60000,
  })
  const rows = q.data || []
  if (!branch || !rows.length) return null

  const run = async (row, live) => {
    if (live && !await confirmBar(`سيتم إرسال طلب ${row.platform} رقم ${row.platform_order} إلى شاشة الكاشير في SOFTECH كبيع آجل على حساب المنصة. متأكد؟`)) return
    setBusy(row.id)
    setNote(n => ({ ...n, [row.id]: null }))
    try {
      await api.post(`/pos-orders/${row.id}/ready/`, {})           // server sets the آجل tender
      const { data } = await api.post(`/pos-orders/${row.id}/push/`, live ? { dry_run: false, confirm: true } : { dry_run: true })
      const text = data.queued ? '⏳ الفرع غير متصل — في الطابور وسيُرسل تلقائياً.'
        : data.live ? `✅ أُرسل للكاشير — مستند SOFTECH ${data.docnumber || data.softech_docnumber || ''}`
        : `✓ المعاينة سليمة — الإجمالي ${money(data.plan?.header?.docvalue ?? data.doc_value)} آجل (لم يُكتب شيء).`
      setNote(n => ({ ...n, [row.id]: { ok: true, text } }))
      qc.invalidateQueries({ queryKey: ['pos', 'platform-drafts'] })
    } catch (e) {
      setNote(n => ({ ...n, [row.id]: { ok: false, text: errText(e) } }))
    } finally { setBusy(null) }
  }

  return (
    <div className="relative" data-tour="pos-platform-drafts">
      <button onClick={() => setOpen(o => !o)} title="طلبات المنصات بانتظار الإرسال للكاشير"
              className="h-8 px-2 rounded border border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100">
        🛵 {rows.length}
      </button>
      {open && (
        <div className="absolute z-30 mt-1 end-0 w-[30rem] max-w-[90vw] bg-white border rounded-lg shadow-lg p-2 text-[12px]">
          <div className="flex items-center justify-between mb-1">
            <b>طلبات المنصات — بيع آجل على حساب المنصة</b>
            <button onClick={() => q.refetch()} className="text-gray-500" title="تحديث">↻</button>
          </div>
          <ul className="divide-y max-h-80 overflow-y-auto">
            {rows.map(r => (
              <li key={r.id} className="py-1.5">
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{r.platform}</span>
                  <span className="text-gray-500" dir="ltr">#{r.platform_order}</span>
                  <span className="text-gray-400 ms-auto">أمر {r.id}</span>
                </div>
                <div className="text-gray-600" dir="ltr">
                  {r.lines.map(l => `${l.name} × ${Number(l.qty)}`).join(' · ')}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <button disabled={busy === r.id} onClick={() => run(r, false)}
                          className="px-2 py-0.5 rounded border hover:bg-gray-50 disabled:opacity-40">🧾 معاينة</button>
                  {writerEnabled && (
                    <button disabled={busy === r.id} onClick={() => run(r, true)}
                            className="px-2 py-0.5 rounded bg-red-600 text-white disabled:opacity-40">⚠ إرسال للكاشير</button>
                  )}
                  {busy === r.id && <span className="text-gray-400">…</span>}
                </div>
                {note[r.id] && <div className={`mt-1 ${note[r.id].ok ? 'text-emerald-700' : 'text-red-600'}`}>{note[r.id].text}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
