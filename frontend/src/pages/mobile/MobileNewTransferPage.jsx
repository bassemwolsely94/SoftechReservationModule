/**
 * MobileNewTransferPage.jsx — phone transfer-request creation (route: /m/transfers/new).
 *
 * Posts to /transfers/ with nested items (TransferRequestCreateSerializer), then
 * either lands on the draft detail or submits immediately. Requesting branch
 * defaults to the user's branch (editable only for HQ roles). Reuses ItemSearchWidget.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { transfersApi, branchesApi } from '../../api/client'
import useAuthStore from '../../store/authStore'
import ItemSearchWidget from '../../components/ItemSearchWidget'

export default function MobileNewTransferPage() {
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const { user } = useAuthStore()
  const canPickRequesting = ['admin', 'purchasing', 'call_center'].includes(user?.role)

  const [requesting, setRequesting] = useState(user?.branch_id ? String(user.branch_id) : '')
  const [supplying, setSupplying]   = useState('')
  const [notes, setNotes]           = useState('')
  const [lines, setLines]           = useState([])   // [{ item, quantity }]
  const [error, setError]           = useState('')
  const [busy, setBusy]             = useState('')    // '' | 'draft' | 'submit'

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => {
      const d = r.data
      return Array.isArray(d) ? d : (d.results ?? [])
    }),
  })

  const addLine    = (item) => setLines(ls => ls.some(l => l.item.id === item.id) ? ls : [...ls, { item, quantity: 1 }])
  const setQty     = (i, q) => setLines(ls => ls.map((l, idx) => idx === i ? { ...l, quantity: q } : l))
  const removeLine = (i)    => setLines(ls => ls.filter((_, idx) => idx !== i))

  async function save(thenSubmit) {
    if (!requesting)                 { setError('حدّد الفرع الطالب'); return }
    if (!supplying)                  { setError('حدّد الفرع المصدر'); return }
    if (String(requesting) === String(supplying)) { setError('الفرع الطالب والمصدر يجب أن يختلفا'); return }
    if (lines.length === 0)          { setError('أضف صنفاً واحداً على الأقل'); return }
    setBusy(thenSubmit ? 'submit' : 'draft'); setError('')
    try {
      const payload = {
        requesting_branch: Number(requesting),
        supplying_branch:  Number(supplying),
        notes,
        items: lines.map(l => ({ item: l.item.id, quantity: Number(l.quantity) || 1 })),
      }
      const { data } = await transfersApi.create(payload)
      if (thenSubmit) {
        try { await transfersApi.submit(data.id) } catch { /* land on detail to retry */ }
      }
      qc.invalidateQueries({ queryKey: ['m-transfers'] })
      navigate(`/m/transfers/${data.id}`, { replace: true })
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'string' ? d : (d?.detail || 'تعذّر إنشاء الطلب'))
      setBusy('')
    }
  }

  return (
    <div className="p-3 space-y-3">
      {/* Branches */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-4">
        <h2 className="font-semibold text-gray-700 text-sm">🔀 الفروع</h2>
        <div>
          <label className="label">الفرع الطالب *</label>
          {canPickRequesting ? (
            <select className="input-field w-full" value={requesting} onChange={e => setRequesting(e.target.value)}>
              <option value="">اختر الفرع...</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          ) : (
            <div className="input-field bg-gray-50 text-gray-600">{user?.branch_name || 'فرعك الحالي'}</div>
          )}
        </div>
        <div>
          <label className="label">الفرع المصدر *</label>
          <select className="input-field w-full" value={supplying} onChange={e => setSupplying(e.target.value)}>
            <option value="">اختر الفرع المصدر...</option>
            {branches.filter(b => String(b.id) !== String(requesting)).map(b => (
              <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Items */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 text-sm mb-2.5">💊 الأصناف *</h2>
        <ItemSearchWidget selected={null} onSelect={addLine} onClear={() => {}}
          placeholder="ابحث وأضف صنفاً..." />
        {lines.length > 0 && (
          <div className="mt-3 space-y-2">
            {lines.map((l, i) => (
              <div key={l.item.id} className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-xl p-2.5">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-800 break-words">{l.item.name}</div>
                  <div className="text-[11px] text-gray-400 font-mono">كود: {l.item.softech_id}</div>
                </div>
                <input
                  type="number" min="1" inputMode="numeric"
                  className="input-field w-20 text-sm"
                  value={l.quantity}
                  onChange={e => setQty(i, e.target.value)}
                />
                <button onClick={() => removeLine(i)} className="text-gray-400 hover:text-red-500 text-sm shrink-0">🗑</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Notes */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <label className="label">ملاحظات</label>
        <textarea rows={2} className="input-field w-full resize-none" value={notes}
          onChange={e => setNotes(e.target.value)} placeholder="سبب الطلب أو أي تفاصيل..." />
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-2xl px-4 py-3">{error}</div>}

      <div className="flex gap-2.5">
        <button onClick={() => save(false)} disabled={!!busy} className="btn-secondary flex-1 disabled:opacity-50">
          {busy === 'draft' ? 'جارٍ الحفظ...' : 'حفظ كمسودة'}
        </button>
        <button onClick={() => save(true)} disabled={!!busy} className="btn-primary flex-1 py-3 disabled:opacity-50">
          {busy === 'submit' ? 'جارٍ التقديم...' : '✅ حفظ وتقديم'}
        </button>
      </div>
    </div>
  )
}
