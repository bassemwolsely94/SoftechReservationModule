/**
 * InsuranceRostersPage — سجل مرضى الجهات: the cumulative patient roster of one جهة
 * (optionally one فئة), derived by the backend from earlier claims, separation lists
 * and reviewer decisions. Read-only: decisions are taken in each claim's «فصل الأسماء».
 */
import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'
import useServerSort from '../hooks/useServerSort'
import SortTh from '../components/SortTh'

const inp = 'border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500'
const SRC = { history: 'مطالبات سابقة', list: 'قائمة', decision: 'قرار مراجع' }
const SORT_KEYS = ['name', 'subclient', 'group_label', 'count', 'last', 'elsewhere']   // the server sorts ALL members before its 3000 cut

export default function InsuranceRostersPage() {
  const navigate = useNavigate()
  const [clients, setClients] = useState([])
  const [subs, setSubs]       = useState([])
  const [clientId, setClientId] = useState('')
  const [subId, setSubId]     = useState('')
  const [q, setQ]             = useState('')
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState(null)
  const [onlyElsewhere, setOnlyElsewhere] = useState(false)
  const [ordering, setOrdering] = useState('')

  useEffect(() => {
    Promise.all([insuranceApi.clients(), insuranceApi.subclients()]).then(([c, sc]) => {
      setClients(c.data.results || c.data); setSubs(sc.data.results || sc.data)
    }).catch(() => {})
  }, [])

  const load = (query = q, order = ordering) => {
    if (!clientId) return
    setLoading(true); setErr(null)
    insuranceApi.rosters({ client_id: clientId, subclient_id: subId || undefined, q: query || undefined, ordering: order || undefined })
      .then(r => setData(r.data))
      .catch(e => setErr(e.response?.data?.error || 'تعذّر تحميل السجل'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [clientId, subId])   // eslint-disable-line

  const members = useMemo(
    () => (data?.members || []).filter(m => !onlyElsewhere || m.other_companies.length),
    [data, onlyElsewhere])
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); load(q, o) }, { allowed: SORT_KEYS })
  const Th = (k, label, type = 'text', align = 'right') => (
    <SortTh {...headerProps(k, type)} className={`text-${align} px-2 py-2 font-semibold whitespace-nowrap`}>{label}</SortTh>
  )
  const clientLabel = (c) => {
    const names = subs.filter(x => x.client === c.id).map(x => x.name).join('، ')
    return names ? `${c.name} — ${names}` : c.name
  }

  return (
    <div className="p-6 space-y-4" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <button onClick={() => navigate('/insurance')} className="text-sm text-blue-600 hover:underline">← مطالبات التأمين</button>
          <h1 className="text-xl font-bold text-gray-800 mt-1">سجل مرضى الجهات</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            كل اسم فُوتر على الجهة فى مطالبات سابقة (غير ملغاة وغير مستبعدة)، أو فى قائمة فصل تتبعها، أو أكّده مراجع —
            يكبر تلقائياً كل شهر. الأسماء المستبعدة بقرار أو بخصم «المريض لا يتبع الجهة» تظهر منفصلة.
          </p>
        </div>
        <button onClick={() => navigate('/insurance/separation-lists')} className="text-xs text-blue-600 hover:underline">⚙ قوائم فصل الأسماء</button>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-wrap items-end gap-3" data-tour="insurance-rosters-filters">
        <label className="text-xs text-gray-500">الجهة
          <select className={`${inp} block mt-0.5 min-w-[280px]`} value={clientId} data-tour="insurance-rosters-client"
            onChange={e => { setClientId(e.target.value); setSubId(''); setData(null) }}>
            <option value="">— اختر الجهة —</option>
            {clients.map(c => <option key={c.id} value={c.id}>{clientLabel(c)}</option>)}
          </select>
        </label>
        <label className="text-xs text-gray-500">الفئة
          <select className={`${inp} block mt-0.5`} value={subId} disabled={!clientId} onChange={e => setSubId(e.target.value)}>
            <option value="">كل الفئات</option>
            {subs.filter(s => String(s.client) === String(clientId)).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <label className="text-xs text-gray-500">بحث بالاسم
          <input className={`${inp} block mt-0.5 w-56`} value={q} disabled={!clientId} data-tour="insurance-rosters-search"
            placeholder="أول حروف كل كلمة…" onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && load()} />
        </label>
        <button onClick={() => load()} disabled={!clientId || loading}
          className="px-3 py-2 bg-blue-600 text-white text-sm rounded disabled:opacity-40">{loading ? 'جارٍ…' : 'عرض'}</button>
      </div>

      {err && <div className="text-sm text-red-600">{err}</div>}
      {!clientId && <div className="text-sm text-gray-400">اختر جهة لعرض سجل مرضاها.</div>}

      {data?.client && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="px-2 py-1 rounded bg-gray-100 text-gray-700">{data.counts.members} اسم فى السجل</span>
            <button onClick={() => setOnlyElsewhere(v => !v)} data-tour="insurance-rosters-elsewhere"
              className={`px-2 py-1 rounded border ${onlyElsewhere ? 'bg-red-600 text-white border-red-600' : 'bg-red-50 text-red-700 border-red-200'}`}>
              ⚑ مُفوتر أيضاً على شركة أخرى: {data.counts.also_elsewhere}</button>
            <span className="px-2 py-1 rounded bg-amber-50 text-amber-800">مستبعد: {data.counts.ruled_out}</span>
            {data.members.length >= 3000 && <span className="text-gray-400">يُعرض أول 3000 — استخدم البحث</span>}
          </div>

          <div className="bg-white rounded-xl border border-gray-200 overflow-auto max-h-[calc(100vh-330px)]" data-tour="insurance-rosters-grid">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200 text-gray-500 text-xs sticky top-0 z-10">
                <tr>
                  {Th('name', 'الاسم')}
                  {Th('subclient', 'الفئة')}
                  {Th('group_label', 'فئة الفوترة')}
                  {Th('count', 'مرات الفوترة', 'number', 'center')}
                  {Th('last', 'آخر فوترة', 'date')}
                  <th className="text-right px-2 py-2 font-semibold">المصدر</th>
                  {Th('elsewhere', 'مُفوتر أيضاً على', 'number')}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {members.map((m, i) => (
                  <tr key={i} className={`hover:bg-gray-50 ${m.other_companies.length ? 'bg-red-50/40' : ''}`}>
                    <td className="px-2 py-1.5 font-medium text-gray-800">{m.name}</td>
                    <td className="px-2 py-1.5 text-gray-600">{m.subclient || '—'}</td>
                    <td className="px-2 py-1.5 text-gray-500 text-xs">{m.group_label || '—'}</td>
                    <td className="px-2 py-1.5 text-center font-mono">{m.count || '—'}</td>
                    <td className="px-2 py-1.5 font-mono text-xs text-gray-600">{m.last || '—'}</td>
                    <td className="px-2 py-1.5 text-xs text-gray-500">{m.sources.map(s => SRC[s] || s).join('، ')}</td>
                    <td className="px-2 py-1.5 text-xs text-red-700">{m.other_companies.join('، ') || <span className="text-gray-300">—</span>}</td>
                  </tr>
                ))}
                {members.length === 0 && <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-400">لا أسماء.</td></tr>}
              </tbody>
            </table>
          </div>

          {data.ruled_out.length > 0 && (
            <details className="bg-white border border-amber-200 rounded-xl p-3" data-tour="insurance-rosters-ruled-out">
              <summary className="text-sm font-semibold text-amber-800 cursor-pointer">أسماء مستبعدة من هذه الجهة ({data.ruled_out.length})</summary>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                {data.ruled_out.map((r, i) => (
                  <span key={i} className="px-2 py-0.5 rounded bg-amber-50 text-amber-900">{r.name}{r.subclient ? ` · ${r.subclient}` : ''}</span>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  )
}
