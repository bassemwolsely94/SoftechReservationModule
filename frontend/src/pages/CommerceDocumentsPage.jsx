/**
 * CommerceDocumentsPage — list + create commerce documents (quotations, retail
 * invoices, allocation grids).  Behind COMMERCE_DOCS_ENABLED; shows a clear
 * disabled state when the flag is off.
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { commerceApi } from '../api/client'

const fmt = n => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function CommerceDocumentsPage() {
  const navigate = useNavigate()
  const [enabled, setEnabled]   = useState(null)
  const [types, setTypes]       = useState([])
  const [docs, setDocs]         = useState([])
  const [recipients, setRecipients] = useState([])
  const [loading, setLoading]   = useState(true)
  const [showNew, setShowNew]   = useState(false)
  const [form, setForm]         = useState({ doc_type: '', recipient: '', doc_date: new Date().toISOString().slice(0, 10) })
  const [err, setErr]           = useState(null)
  const [newRecip, setNewRecip] = useState('')

  const addRecipient = async () => {
    if (!newRecip.trim()) return
    const { data } = await commerceApi.createRecipient({ name: newRecip.trim(), kind: 'hospital' })
    setRecipients(rs => [...rs, data])
    setForm(f => ({ ...f, recipient: String(data.id) }))
    setNewRecip('')
  }

  const load = () => {
    setLoading(true)
    commerceApi.status()
      .then(r => {
        setEnabled(r.data.enabled)
        setTypes(r.data.types || [])
        if (r.data.enabled) {
          commerceApi.documents().then(d => setDocs(d.data.results || d.data))
          commerceApi.recipients().then(d => setRecipients(d.data.results || d.data))
        }
      })
      .catch(() => setEnabled(false))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    setErr(null)
    if (!form.doc_type) { setErr('اختر نوع المستند'); return }
    try {
      const { data } = await commerceApi.createDocument({
        doc_type: form.doc_type,
        recipient: form.recipient || null,
        doc_date: form.doc_date,
      })
      navigate(`/commerce/documents/${data.id}`)
    } catch (e) {
      setErr(e.response?.data?.error || 'تعذّر الإنشاء')
    }
  }

  if (loading) return <div className="p-8 text-center text-gray-400">جارٍ التحميل…</div>
  if (enabled === false) return (
    <div className="p-10 max-w-lg mx-auto text-center">
      <div className="text-4xl mb-3">🧩</div>
      <h2 className="text-lg font-semibold text-gray-800 mb-2">وحدة المستندات التجارية غير مُفعَّلة</h2>
      <p className="text-sm text-gray-500">فعّلها بضبط <code className="bg-gray-100 px-1 rounded">COMMERCE_DOCS_ENABLED=true</code> ثم إعادة تشغيل السيرفر.</p>
    </div>
  )

  return (
    <div className="p-6" dir="rtl">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-bold text-gray-800">المستندات التجارية</h1>
          <p className="text-sm text-gray-500">عروض أسعار · فواتير بيع · شبكات توزيع المستشفيات</p>
        </div>
        <button onClick={() => { setForm({ doc_type: '', recipient: '', doc_date: new Date().toISOString().slice(0, 10) }); setShowNew(true) }}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">+ مستند جديد</button>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>{['رقم المستند', 'النوع', 'الجهة', 'التاريخ', 'الحالة', 'البنود', 'الإجمالى', ''].map(h =>
              <th key={h} className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 whitespace-nowrap">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {docs.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-12 text-gray-400">لا توجد مستندات — أنشئ أول مستند</td></tr>
            ) : docs.map(d => (
              <tr key={d.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => navigate(`/commerce/documents/${d.id}`)}>
                <td className="px-3 py-2.5 font-mono text-blue-700 font-semibold">{d.number}</td>
                <td className="px-3 py-2.5 text-gray-700">{d.type_name}</td>
                <td className="px-3 py-2.5 text-gray-700">{d.recipient_name || '—'}</td>
                <td className="px-3 py-2.5 text-gray-500 text-xs">{d.doc_date}</td>
                <td className="px-3 py-2.5"><span className="text-xs bg-gray-100 text-gray-600 rounded px-2 py-0.5">{d.status}</span></td>
                <td className="px-3 py-2.5 text-center text-gray-600">{d.line_count}</td>
                <td className="px-3 py-2.5 text-left font-mono font-semibold">{fmt(d.total)}</td>
                <td className="px-3 py-2.5 text-left text-blue-600 text-xs">فتح ←</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showNew && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setShowNew(false)}>
          <div className="bg-white rounded-xl p-5 w-96 max-w-[92vw]" dir="rtl" onClick={e => e.stopPropagation()}>
            <h3 className="font-semibold text-gray-800 mb-3">مستند جديد</h3>
            <label className="text-xs text-gray-600 block mb-1">النوع *</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-3"
              value={form.doc_type} onChange={e => setForm(f => ({ ...f, doc_type: e.target.value }))}>
              <option value="">اختر…</option>
              {types.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <label className="text-xs text-gray-600 block mb-1">الجهة (اختياري)</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-2"
              value={form.recipient} onChange={e => setForm(f => ({ ...f, recipient: e.target.value }))}>
              <option value="">— بدون —</option>
              {recipients.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
            <div className="flex gap-2 mb-3">
              <input className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm" placeholder="+ جهة جديدة (مستشفى)…"
                value={newRecip} onChange={e => setNewRecip(e.target.value)} onKeyDown={e => e.key === 'Enter' && addRecipient()} />
              <button onClick={addRecipient} disabled={!newRecip.trim()}
                className="text-xs px-2 bg-sky-600 text-white rounded hover:bg-sky-700 disabled:opacity-50">إضافة</button>
            </div>
            <label className="text-xs text-gray-600 block mb-1">التاريخ</label>
            <input type="date" className="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-3"
              value={form.doc_date} onChange={e => setForm(f => ({ ...f, doc_date: e.target.value }))} />
            {err && <p className="text-red-600 text-xs mb-2">{err}</p>}
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowNew(false)} className="px-3 py-2 text-sm text-gray-600">إلغاء</button>
              <button onClick={create} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">إنشاء وفتح</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
