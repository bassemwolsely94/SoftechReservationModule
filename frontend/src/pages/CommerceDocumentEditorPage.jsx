/**
 * CommerceDocumentEditorPage — edit a document's lines (hand-typed item, price,
 * qty, VAT flag), see live inclusive-VAT totals, and export.
 */
import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { commerceApi } from '../api/client'
import CommerceAllocationGrid from './CommerceAllocationGrid'

const fmt = n => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function CommerceDocumentEditorPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [doc, setDoc]   = useState(null)
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState({ item_name: '', unit_price: '', quantity: '1', vat_applicable: false })
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)

  const load = () => commerceApi.document(id).then(r => setDoc(r.data)).finally(() => setLoading(false))
  useEffect(() => { load() }, [id])

  const addLine = async () => {
    if (!draft.item_name.trim()) return
    setSaving(true)
    try {
      await commerceApi.addLine(id, {
        item_name: draft.item_name.trim(),
        unit_price: draft.unit_price || 0,
        quantity: draft.quantity || 0,
        vat_applicable: draft.vat_applicable,
      })
      setDraft({ item_name: '', unit_price: '', quantity: '1', vat_applicable: false })
      await load()
    } finally { setSaving(false) }
  }

  const patchLine = async (lid, patch) => { await commerceApi.editLine(id, lid, patch); await load() }
  const delLine   = async (lid) => { if (window.confirm('حذف البند؟')) { await commerceApi.deleteLine(id, lid); await load() } }

  const exportDoc = async () => {
    setExporting(true)
    try {
      const { data: blob } = await commerceApi.exportDocument(id)
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
      const a = document.createElement('a'); a.href = url; a.download = `${doc.number}.xlsx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
    } finally { setExporting(false) }
  }

  if (loading) return <div className="p-8 text-center text-gray-400">جارٍ التحميل…</div>
  if (!doc) return <div className="p-8 text-center text-red-500">المستند غير موجود</div>

  const inp = 'border border-gray-300 rounded px-2 py-1.5 text-sm'

  return (
    <div className="p-6" dir="rtl">
      <button onClick={() => navigate('/commerce')} className="text-sm text-gray-500 hover:text-gray-700 mb-3">← المستندات التجارية</button>
      <div className="flex items-start justify-between flex-wrap gap-3 mb-5">
        <div>
          <h1 className="text-xl font-bold text-gray-800">{doc.type_name} — <span className="font-mono text-blue-700">{doc.number}</span></h1>
          <p className="text-sm text-gray-500">{doc.recipient_name || 'بدون جهة'} · {doc.doc_date} · ض.ق.م {fmt(doc.vat_rate)}%</p>
        </div>
        <button onClick={exportDoc} disabled={exporting}
          className="px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 disabled:opacity-50">
          {exporting ? 'جارٍ…' : '⬇ تصدير Excel'}
        </button>
      </div>

      {/* Allocation documents show the branch-quantity matrix instead of the line editor */}
      {doc.is_allocation ? (
        <CommerceAllocationGrid doc={doc} onTotals={() => load()} />
      ) : (
      <>
      {/* Totals cards */}
      <div className="grid grid-cols-3 gap-3 mb-5 max-w-xl">
        {[['الإجمالى قبل الضريبة', doc.subtotal_ex_vat, 'text-gray-700'],
          ['إجمالى الضريبة', doc.vat_total, 'text-orange-600'],
          ['الإجمالى شامل الضريبة', doc.total, 'text-gray-900']].map(([k, v, c]) => (
          <div key={k} className="bg-white border border-gray-200 rounded-xl p-3">
            <p className="text-xs text-gray-500">{k}</p>
            <p className={`font-mono font-bold mt-1 ${c}`}>{fmt(v)}</p>
          </div>
        ))}
      </div>

      {/* Lines */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>{['م', 'الصنف', 'الكمية', 'سعر الوحدة (شامل)', 'خاضع للضريبة', 'الضريبة', 'الإجمالى', ''].map(h =>
              <th key={h} className="text-right px-3 py-2 text-xs font-semibold text-gray-500 whitespace-nowrap">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {doc.lines.map((l, i) => (
              <tr key={l.id}>
                <td className="px-3 py-2 text-gray-400 text-xs">{i + 1}</td>
                <td className="px-3 py-2">
                  <input className={`${inp} w-44`} defaultValue={l.item_name}
                    onBlur={e => e.target.value !== l.item_name && patchLine(l.id, { item_name: e.target.value })} />
                </td>
                <td className="px-3 py-2">
                  <input type="number" step="0.01" className={`${inp} w-20 text-left`} defaultValue={l.quantity}
                    onBlur={e => Number(e.target.value) !== Number(l.quantity) && patchLine(l.id, { quantity: e.target.value })} />
                </td>
                <td className="px-3 py-2">
                  <input type="number" step="any" className={`${inp} w-24 text-left`} defaultValue={l.unit_price}
                    onBlur={e => Number(e.target.value) !== Number(l.unit_price) && patchLine(l.id, { unit_price: e.target.value })} />
                </td>
                <td className="px-3 py-2 text-center">
                  <input type="checkbox" checked={l.vat_applicable}
                    onChange={e => patchLine(l.id, { vat_applicable: e.target.checked })} />
                </td>
                <td className="px-3 py-2 text-left font-mono text-orange-600 text-xs">{fmt(l.vat_amount)}</td>
                <td className="px-3 py-2 text-left font-mono font-semibold">{fmt(l.line_total)}</td>
                <td className="px-3 py-2 text-left">
                  <button onClick={() => delLine(l.id)} className="text-red-500 hover:text-red-700 text-xs">حذف</button>
                </td>
              </tr>
            ))}
            {/* Add-line row */}
            <tr className="bg-blue-50/40">
              <td className="px-3 py-2 text-gray-300">+</td>
              <td className="px-3 py-2"><input className={`${inp} w-44`} placeholder="اسم الصنف…" value={draft.item_name}
                onChange={e => setDraft(d => ({ ...d, item_name: e.target.value }))} onKeyDown={e => e.key === 'Enter' && addLine()} /></td>
              <td className="px-3 py-2"><input type="number" step="0.01" className={`${inp} w-20 text-left`} value={draft.quantity}
                onChange={e => setDraft(d => ({ ...d, quantity: e.target.value }))} /></td>
              <td className="px-3 py-2"><input type="number" step="any" className={`${inp} w-24 text-left`} placeholder="السعر" value={draft.unit_price}
                onChange={e => setDraft(d => ({ ...d, unit_price: e.target.value }))} /></td>
              <td className="px-3 py-2 text-center"><input type="checkbox" checked={draft.vat_applicable}
                onChange={e => setDraft(d => ({ ...d, vat_applicable: e.target.checked }))} /></td>
              <td colSpan={2} className="px-3 py-2 text-gray-400 text-xs">14% شاملة في السعر إن فُعِّلت</td>
              <td className="px-3 py-2 text-left">
                <button onClick={addLine} disabled={saving || !draft.item_name.trim()}
                  className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50">إضافة</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-gray-400 mt-2">الأسعار شاملة الضريبة؛ يُحتسب جزء الـ 14% تلقائياً للأصناف المُعلَّمة فقط (لا يُضاف فوق السعر).</p>
      </>
      )}
    </div>
  )
}
