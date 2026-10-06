/**
 * MobileNewDemandPage.jsx — capture unmet demand at the counter (route: /m/demand/new).
 *
 * Phone is the mandatory identifier. Items can be catalog matches or free-text
 * (uncoded). Posts to /demand/ (DemandCreateSerializer with nested items).
 * Branch defaults to the user's; admin/call_center may pick.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi } from '../../api/client'
import { queuedPost } from '../../api/offlineQueue'
import useAuthStore from '../../store/authStore'
import ItemSearchWidget from '../../components/ItemSearchWidget'
import { DEMAND_PRIORITIES, DEMAND_SOURCES } from './demandStatus'

export default function MobileNewDemandPage() {
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const { user } = useAuthStore()
  const canPickBranch = ['admin', 'call_center'].includes(user?.role)

  const [phone, setPhone]       = useState('')
  const [name, setName]         = useState('')
  const [branch, setBranch]     = useState(user?.branch_id ? String(user.branch_id) : '')
  const [priority, setPriority] = useState('normal')
  const [source, setSource]     = useState('walk_in')
  const [notes, setNotes]       = useState('')
  const [lines, setLines]       = useState([])   // [{ key, item|null, free, quantity }]
  const [manualName, setManualName] = useState('')
  const [busy, setBusy]         = useState(false)
  const [error, setError]       = useState('')

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => {
      const d = r.data
      return Array.isArray(d) ? d : (d.results ?? [])
    }),
    enabled: canPickBranch,
  })

  const addCatalog = (item) => setLines(ls => ls.some(l => l.item?.id === item.id)
    ? ls : [...ls, { key: `c${item.id}`, item, free: '', quantity: 1 }])
  const addManual = () => {
    const n = manualName.trim()
    if (!n) return
    setLines(ls => [...ls, { key: `m${Date.now()}`, item: null, free: n, quantity: 1 }])
    setManualName('')
  }
  const setQty     = (k, q) => setLines(ls => ls.map(l => l.key === k ? { ...l, quantity: q } : l))
  const removeLine = (k)    => setLines(ls => ls.filter(l => l.key !== k))

  async function submit() {
    if (!phone.trim())  { setError('رقم الهاتف مطلوب'); return }
    if (!branch)        { setError('حدّد الفرع'); return }
    if (lines.length === 0) { setError('أضف صنفاً واحداً على الأقل'); return }
    setBusy(true); setError('')
    try {
      const payload = {
        phone: phone.trim(),
        customer_name: name.trim(),
        branch: Number(branch),
        priority, source, notes,
        items: lines.map(l => l.item
          ? { item: l.item.id, quantity: Number(l.quantity) || 1 }
          : { item_name_free: l.free, quantity: Number(l.quantity) || 1 }),
      }
      const res = await queuedPost('/demand/', payload, { label: 'تسجيل طلب' })
      qc.invalidateQueries({ queryKey: ['m-demand'] })
      if (res.queued) {
        navigate('/m/demand', { replace: true })   // created on reconnect
        return
      }
      navigate(`/m/demand/${res.data.id}`, { replace: true })
    } catch (e) {
      const d = e.response?.data
      let msg = 'تعذّر التسجيل'
      if (typeof d === 'string') msg = d
      else if (d?.detail) msg = d.detail
      else if (d?.phone) msg = Array.isArray(d.phone) ? d.phone.join(' ') : String(d.phone)
      else if (d) { const p = Object.entries(d).map(([f, m]) => `${f}: ${Array.isArray(m) ? m.join(' ') : m}`); if (p.length) msg = p.join(' | ') }
      setError(msg)
      setBusy(false)
    }
  }

  return (
    <div className="p-3 space-y-3">
      {/* Customer */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-3">
        <h2 className="font-semibold text-gray-700 text-sm">👤 العميل</h2>
        <div>
          <label className="label">رقم الهاتف *</label>
          <input className="input-field w-full" dir="ltr" inputMode="tel" type="tel"
            placeholder="01xxxxxxxxx" value={phone} onChange={e => setPhone(e.target.value)} />
        </div>
        <div>
          <label className="label">الاسم (اختياري)</label>
          <input className="input-field w-full" value={name} onChange={e => setName(e.target.value)} />
        </div>
      </div>

      {/* Items */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <h2 className="font-semibold text-gray-700 text-sm mb-2.5">💊 الأصناف المطلوبة *</h2>
        <ItemSearchWidget selected={null} onSelect={addCatalog} onClear={() => {}}
          placeholder="ابحث وأضف صنفاً..." />
        <div className="flex gap-2 mt-2">
          <input className="input-field flex-1 text-sm" placeholder="أو اكتب اسم صنف غير مكوَّد..."
            value={manualName} onChange={e => setManualName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addManual() }} />
          <button onClick={addManual} disabled={!manualName.trim()}
            className="btn-secondary text-sm px-4 disabled:opacity-50">إضافة</button>
        </div>

        {lines.length > 0 && (
          <div className="mt-3 space-y-2">
            {lines.map(l => (
              <div key={l.key} className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-xl p-2.5">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-800 break-words">{l.item ? l.item.name : l.free}</div>
                  <div className="text-[11px] text-gray-400">{l.item ? `كود: ${l.item.softech_id}` : 'غير مكوَّد'}</div>
                </div>
                <input type="number" min="1" inputMode="numeric" className="input-field w-16 text-sm"
                  value={l.quantity} onChange={e => setQty(l.key, e.target.value)} />
                <button onClick={() => removeLine(l.key)} className="text-gray-400 hover:text-red-500 text-sm shrink-0">🗑</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Details */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-4">
        {canPickBranch ? (
          <div>
            <label className="label">الفرع *</label>
            <select className="input-field w-full" value={branch} onChange={e => setBranch(e.target.value)}>
              <option value="">اختر الفرع...</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          </div>
        ) : (
          <div>
            <label className="label">الفرع</label>
            <div className="input-field bg-gray-50 text-gray-600">{user?.branch_name || 'فرعك الحالي'}</div>
          </div>
        )}
        <div>
          <label className="label">الأولوية</label>
          <div className="grid grid-cols-4 gap-1.5">
            {DEMAND_PRIORITIES.map(p => (
              <button key={p.value} onClick={() => setPriority(p.value)}
                className={`py-2 rounded-xl border-2 text-xs font-semibold transition-all ${
                  priority === p.value ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-gray-200 bg-white text-gray-600'
                }`}>{p.label}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="label">المصدر</label>
          <div className="grid grid-cols-4 gap-1.5">
            {DEMAND_SOURCES.map(s => (
              <button key={s.value} onClick={() => setSource(s.value)}
                className={`py-2 rounded-xl border-2 text-xs font-semibold transition-all ${
                  source === s.value ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-gray-200 bg-white text-gray-600'
                }`}>{s.label}</button>
            ))}
          </div>
        </div>
        <div>
          <label className="label">ملاحظات</label>
          <textarea rows={2} className="input-field w-full resize-none" value={notes}
            onChange={e => setNotes(e.target.value)} placeholder="أي تفاصيل..." />
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-2xl px-4 py-3">{error}</div>}

      <div className="flex gap-2.5">
        <button onClick={() => navigate('/m/demand')} className="btn-secondary px-5">إلغاء</button>
        <button onClick={submit} disabled={busy} className="btn-primary flex-1 py-3 disabled:opacity-50">
          {busy ? 'جارٍ التسجيل...' : '✅ تسجيل الطلب'}
        </button>
      </div>
    </div>
  )
}
