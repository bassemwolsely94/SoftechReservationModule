/**
 * MobileFridgeLogPage.jsx — C31 fridge temperature log (route: /m/qa/fridge).
 *
 * Two readings a day per fridge (morning / evening): current, min and max since the last reading,
 * and the reader's initials. The server decides "out of range", refuses a second reading for the
 * same slot and keeps readings append-only. The month sheet below prints as the paper log EDA asks for.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { qaApi, branchesApi } from '../../api/client'
import useAuthStore from '../../store/authStore'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import { cairoToday } from '../../utils/cairoDate'

function cairoHour() {
  return Number(new Intl.DateTimeFormat('en-GB', { hour: '2-digit', hour12: false, timeZone: 'Africa/Cairo' }).format(new Date()))
}

function Cell({ r }) {
  if (!r || r.missing === false) return <td className="border px-1 py-0.5 text-gray-300">·</td>
  if (r.missing) return <td className="border px-1 py-0.5 bg-red-50 text-red-600 font-bold">✗</td>
  return (
    <td className={`border px-1 py-0.5 ${r.out_of_range ? 'bg-red-100 text-red-700 font-bold' : ''}`}>
      {r.temp_c}
      <span className="text-[10px] text-gray-500"> ({r.min_seen_c ?? '—'}/{r.max_seen_c ?? '—'})</span>
      <div className="text-[10px] text-gray-500">{r.initials}{r.late ? ' · متأخر' : ''}</div>
    </td>
  )
}

export default function MobileFridgeLogPage() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canPickBranch = !!user?.sees_all_branches   // server decides (core.branch_scope); it also scopes every call
  const [branch, setBranch] = useState(user?.branch_id ? String(user.branch_id) : '')
  const [fridgeId, setFridgeId] = useState('')
  const [month, setMonth] = useState(cairoToday().slice(0, 7))
  const [form, setForm] = useState({ slot: cairoHour() < 14 ? 'am' : 'pm', temp_c: '', min_seen_c: '', max_seen_c: '', initials: '', note: '' })
  const [newName, setNewName] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const branches = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => { const d = r.data; return Array.isArray(d) ? d : (d.results ?? []) }),
    enabled: canPickBranch,
  })
  const fridges = useQuery({
    queryKey: ['qa-fridges', branch],
    queryFn: () => qaApi.fridges({ active: 1, ...(branch ? { branch } : {}) }).then(r => r.data?.results || r.data),
  })
  const list = Array.isArray(fridges.data) ? fridges.data : []
  const current = list.find(f => String(f.id) === String(fridgeId)) || list[0]
  const sheet = useQuery({
    queryKey: ['qa-fridge-month', current?.id, month],
    queryFn: () => qaApi.fridgeMonth(current.id, month).then(r => r.data),
    enabled: !!current,
  })

  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  async function save() {
    if (!current) return
    if (form.temp_c === '' || !form.initials.trim()) { setMsg({ err: true, t: 'الدرجة الحالية والتوقيع مطلوبين' }); return }
    setBusy(true); setMsg(null)
    const body = { fridge: current.id, day: cairoToday(), slot: form.slot, temp_c: form.temp_c,
                   initials: form.initials.trim(), note: form.note.trim(),
                   ...(form.min_seen_c !== '' ? { min_seen_c: form.min_seen_c } : {}),
                   ...(form.max_seen_c !== '' ? { max_seen_c: form.max_seen_c } : {}) }
    try {
      const { data } = await qaApi.recordFridgeReading(body)
      setMsg(data.out_of_range
        ? { err: true, t: `اتسجلت — خارج النطاق (${current.min_c}–${current.max_c}°م). الفرع اتبلّغ؛ اكتب الإجراء في ملاحظة القراءة الجاية.` }
        : { err: false, t: 'اتسجلت القراءة ✓' })
      setForm(f => ({ ...f, temp_c: '', min_seen_c: '', max_seen_c: '', note: '' }))
      qc.invalidateQueries({ queryKey: ['qa-fridge-month'] })
    } catch (e) {
      const d = e.response?.data || {}
      setMsg({ err: true, t: d.detail || Object.values(d).flat()[0] || 'تعذّر الحفظ' })
    } finally { setBusy(false) }
  }

  async function addFridge() {
    if (!newName.trim() || !branch) { setMsg({ err: true, t: 'اكتب اسم الثلاجة وحدد الفرع' }); return }
    setBusy(true); setMsg(null)
    try {
      const { data } = await qaApi.createFridge({ branch: Number(branch), name: newName.trim() })
      setNewName(''); setFridgeId(String(data.id))
      qc.invalidateQueries({ queryKey: ['qa-fridges'] })
    } catch (e) {
      const d = e.response?.data || {}
      setMsg({ err: true, t: d.detail || Object.values(d).flat()[0] || 'تعذّر الإضافة' })
    } finally { setBusy(false) }
  }

  return (
    <div className="p-3 space-y-3">
      <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-3 print:hidden" data-tour="hr-qa-fridge-pick">
        {canPickBranch && (
          <select className="input-field w-full" value={branch} onChange={e => { setBranch(e.target.value); setFridgeId('') }}>
            <option value="">كل الفروع</option>
            {(branches.data || []).map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
        )}
        {fridges.isLoading ? <MobileLoading />
          : fridges.isError ? <MobileError text="تعذّر تحميل الثلاجات" onRetry={fridges.refetch} />
          : list.length === 0 ? <MobileEmpty icon="🌡️" text="مفيش ثلاجة متسجلة للفرع ده لسه" />
          : (
            <select className="input-field w-full" value={current?.id || ''} onChange={e => setFridgeId(e.target.value)}>
              {list.map(f => <option key={f.id} value={f.id}>{f.name} — {f.branch_name} ({f.min_c}–{f.max_c}°م)</option>)}
            </select>
          )}
        <div className="flex gap-2">
          <input className="input-field flex-1" placeholder="اسم ثلاجة جديدة..." value={newName} onChange={e => setNewName(e.target.value)} />
          <button onClick={addFridge} disabled={busy || !branch} className="btn-secondary disabled:opacity-50">إضافة</button>
        </div>
      </div>

      {current && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-3 print:hidden" data-tour="hr-qa-fridge-form">
          <div className="flex gap-2">
            {[['am', 'صباحاً'], ['pm', 'مساءً']].map(([v, l]) => (
              <button key={v} onClick={() => setForm(f => ({ ...f, slot: v }))}
                className={`flex-1 rounded-lg border py-1.5 text-sm ${form.slot === v ? 'bg-brand-600 text-white' : 'text-gray-600'}`}>{l}</button>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            <label className="text-xs text-gray-600">الحالية °م *<input type="number" step="0.1" className="input-field w-full" value={form.temp_c} onChange={set('temp_c')} /></label>
            <label className="text-xs text-gray-600">أقل °م<input type="number" step="0.1" className="input-field w-full" value={form.min_seen_c} onChange={set('min_seen_c')} /></label>
            <label className="text-xs text-gray-600">أعلى °م<input type="number" step="0.1" className="input-field w-full" value={form.max_seen_c} onChange={set('max_seen_c')} /></label>
          </div>
          <input className="input-field w-full" placeholder="التوقيع (الأحرف الأولى) *" value={form.initials} onChange={set('initials')} />
          <input className="input-field w-full" placeholder="ملاحظة / الإجراء (اختياري)" value={form.note} onChange={set('note')} />
          {msg && <div className={`text-sm ${msg.err ? 'text-red-600' : 'text-green-700'}`}>{msg.t}</div>}
          <button data-tour="hr-qa-fridge-save" onClick={save} disabled={busy} className="btn-primary w-full disabled:opacity-50">{busy ? '...' : 'تسجيل القراءة'}</button>
        </div>
      )}

      {current && (
        <div className="bg-white rounded-2xl border border-gray-200 p-3 space-y-2" data-tour="hr-qa-fridge-sheet">
          <div className="flex items-center gap-2 print:hidden">
            <input type="month" className="input-field flex-1" value={month} onChange={e => setMonth(e.target.value)} />
            <button onClick={() => window.print()} className="btn-secondary">🖨️ طباعة</button>
          </div>
          {sheet.data && (
            <>
              <div className="text-sm font-semibold">
                سجل حرارة {sheet.data.fridge.name} — {sheet.data.fridge.branch_name} — {sheet.data.month}
                <span className="font-normal text-gray-600"> · النطاق {sheet.data.fridge.min_c}–{sheet.data.fridge.max_c}°م
                  · الاكتمال {sheet.data.completeness_pct ?? '—'}% · خارج النطاق {sheet.data.out_of_range}</span>
              </div>
              <table className="w-full text-xs text-center border-collapse">
                <thead><tr className="bg-gray-50"><th className="border px-1">اليوم</th><th className="border px-1">صباحاً</th><th className="border px-1">مساءً</th></tr></thead>
                <tbody>
                  {sheet.data.rows.map(r => (
                    <tr key={r.day}><td className="border px-1">{r.day.slice(8)}</td><Cell r={r.am} /><Cell r={r.pm} /></tr>
                  ))}
                </tbody>
              </table>
              <p className="text-[10px] text-gray-500">الخلية: الحالية (أقل/أعلى) · التوقيع. ✗ = قراءة فايتة. الأحمر = خارج النطاق.</p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
