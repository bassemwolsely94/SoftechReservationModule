/**
 * NearExpiryWorklistTab — «🧭 قائمة عمل قرب الانتهاء» on /batches (C04 / P-28).
 *
 * Lots that will not sell before they expire (the FEFO at-risk rule), ranked by money at risk, with ONE
 * suggested action each in the owner's order: return → move → sell-first corner → accept loss. A person
 * picks the action; «ماذا حدث؟» shows what really happened N days later (from the stock ledger).
 * The server decides the list, the suggestion, scope and permissions; this screen only shows them.
 * Nothing here writes to SOFTECH or changes a price — «بيع أولاً» is a shelf flag only.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { batchesApi, transfersApi } from '../api/client'
import DataFreshnessBar from './DataFreshnessBar'
import useBranchLabels from '../hooks/useBranchLabels'
import useGridKeyboard, { GRID_KEYS_HINT } from '../hooks/useGridKeyboard'
import useSortableRows from '../hooks/useSortableRows'
import SortTh from './SortTh'
import MultiSelectFilter from './MultiSelectFilter'
import SavedViewsMenu from './SavedViewsMenu'
import useSavedViews from '../hooks/useSavedViews'

const fmtNum = (n, d = 0) => Number(n ?? 0).toLocaleString('en-US', { maximumFractionDigits: d })
const ACTIONS = [
  { key: 'return',      label: 'مرتجع',      cls: 'bg-indigo-100 text-indigo-700' },
  { key: 'move',        label: 'نقل',        cls: 'bg-emerald-100 text-emerald-700' },
  { key: 'sell_first',  label: 'بيع أولاً',   cls: 'bg-amber-100 text-amber-800' },
  { key: 'accept_loss', label: 'خسارة',      cls: 'bg-red-100 text-red-700' },
]
const ACTION_CLS = Object.fromEntries(ACTIONS.map(a => [a.key, a.cls]))
const ACTION_SHORT = Object.fromEntries(ACTIONS.map(a => [a.key, a.label]))
const OUTCOME_CLS = { sold: 'bg-green-100 text-green-700', moved: 'bg-emerald-100 text-emerald-700',
                      returned: 'bg-indigo-100 text-indigo-700', written_off: 'bg-red-100 text-red-700',
                      expired: 'bg-red-100 text-red-700', on_hand: 'bg-gray-100 text-gray-600',
                      mixed: 'bg-sky-100 text-sky-700', unexplained: 'bg-orange-100 text-orange-700' }

const rowVal = (r, k) => (k === 'item' ? (r.item_name || r.item_code)
  : k === 'suggested' ? r.suggested_label : k === 'chosen' ? (r.action?.chosen_label || '') : r[k])

function Detail({ r }) {
  const d = r.detail || {}
  if (d.return) {
    return (
      <div className="text-xs">
        {d.return.supplier_name || d.return.supplier_code} · <span className="text-gray-500">{d.return.confidence_label}</span>
        <div className="text-red-600">أرسل للرئيسي قبل {d.return.send_by}</div>
        {d.return.history && <div className="text-gray-400">{d.return.history}</div>}
      </div>
    )
  }
  if (d.move?.length) {
    return (
      <div className="text-xs">
        {d.move.map(m => <div key={m.to}>→ {m.to_name} {fmtNum(m.qty)} <span className="text-gray-400">({fmtNum(m.target_rate_month, 1)}/شهر)</span></div>)}
      </div>
    )
  }
  if (r.suggested_action === 'sell_first') {
    return <div className="text-xs text-amber-800">ركن قرب الانتهاء — لا تصرفه لمريض علاجه أطول من الصلاحية</div>
  }
  return <span className="text-gray-300">—</span>
}

function Outcomes({ branch }) {
  const bl = useBranchLabels()
  const params = branch.length ? { branch: branch.join(',') } : {}
  const { data, isLoading } = useQuery({
    queryKey: ['batches', 'near-expiry-outcomes', params],
    queryFn: () => batchesApi.nearExpiryOutcomes(params).then(r => r.data),
  })
  const { sorted, headerProps: h } = useSortableRows(data?.rows || [], { getValue: rowVal })
  const t = data?.totals
  return (
    <div>
      {t && (
        <div className="flex flex-wrap gap-3 mb-3 text-sm">
          <div className="bg-white border rounded-xl px-4 py-2"><div className="text-xs text-gray-500">أُنقذ (بيع / نقل / مرتجع)</div><div className="font-bold text-emerald-700">{fmtNum(t.saved_value)} ج</div></div>
          <div className="bg-white border rounded-xl px-4 py-2"><div className="text-xs text-gray-500">ضاع (انتهى / هالك)</div><div className="font-bold text-red-700">{fmtNum(t.lost_value)} ج</div></div>
          <div className="bg-white border rounded-xl px-4 py-2"><div className="text-xs text-gray-500">مُقاس / منتظر</div><div className="font-bold">{t.closed} / {t.open}</div></div>
        </div>
      )}
      {isLoading ? <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div> : !sorted.length ? (
        <div className="text-center py-14 text-gray-400">لم يُسجَّل أي إجراء بعد.</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead><tr className="bg-gray-50 border-b text-gray-600">
              <SortTh {...h('item', 'text')} className="px-2 py-2 text-right">الصنف</SortTh>
              <SortTh {...h('branch_code', 'text')} className="px-2 py-2 text-right">الفرع</SortTh>
              <SortTh {...h('expiry_date', 'date')} className="px-2 py-2 text-right">الصلاحية</SortTh>
              <SortTh {...h('chosen', 'text')} className="px-2 py-2 text-right">الإجراء</SortTh>
              <SortTh {...h('t0_value', 'number')} className="px-2 py-2 text-right">القيمة المعرّضة</SortTh>
              <SortTh {...h('due_date', 'date')} className="px-2 py-2 text-right">القياس</SortTh>
              <SortTh {...h('outcome_label', 'text')} className="px-2 py-2 text-right">النتيجة</SortTh>
              <SortTh {...h('saved_value', 'number')} className="px-2 py-2 text-right">أُنقذ</SortTh>
              <SortTh {...h('lost_value', 'number')} className="px-2 py-2 text-right">ضاع</SortTh>
            </tr></thead>
            <tbody>
              {sorted.map(r => (
                <tr key={r.id} className="border-b border-gray-100">
                  <td className="px-2 py-1.5">{r.item_name || r.item_code}<div className="text-[11px] text-gray-400">{r.item_code} · {r.batch_no || '—'}</div></td>
                  <td className="px-2 py-1.5 text-xs">{bl(r.branch_code)}</td>
                  <td className="px-2 py-1.5">{r.expiry_date}</td>
                  <td className="px-2 py-1.5"><span className={`px-2 py-0.5 rounded-full text-xs ${ACTION_CLS[r.chosen_action]}`}>{ACTION_SHORT[r.chosen_action]}</span>
                    {r.transfer && <span className="text-xs text-gray-500"> {r.transfer}</span>}</td>
                  <td className="px-2 py-1.5">{fmtNum(r.t0_value)}</td>
                  <td className="px-2 py-1.5 text-xs">{r.status === 'open' ? `بعد ${r.due_date}` : r.due_date}</td>
                  <td className="px-2 py-1.5">
                    {r.outcome ? <span className={`px-2 py-0.5 rounded-full text-xs ${OUTCOME_CLS[r.outcome] || ''}`}>{r.outcome_label}</span> : <span className="text-gray-300">—</span>}
                    {r.outcome_qty && Object.keys(r.outcome_qty).length > 1 && (
                      <div className="text-[11px] text-gray-400">{Object.entries(r.outcome_qty).map(([k, q]) => `${data.outcome_labels[k] || k} ${fmtNum(q, 2)}`).join(' · ')}</div>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-emerald-700">{r.status === 'closed' ? fmtNum(r.saved_value) : ''}</td>
                  <td className="px-2 py-1.5 text-red-700">{r.status === 'closed' ? fmtNum(r.lost_value) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const NE_SV_KEYS = ['branch', 'action']

export default function NearExpiryWorklistTab() {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [view, setView] = useState('list')
  const [branch, setBranch] = useState([])
  const [actionF, setActionF] = useState('')
  // C23 saved views: branches + suggested-action filter
  const sv = useSavedViews('batches.near_expiry', {
    keys: NE_SV_KEYS,
    getFilters: () => ({ branch, action: actionF }),
    applyFilters: f => { setBranch(f.branch || []); setActionF(f.action || '') },
  })
  const [ticked, setTicked] = useState({})
  const [bulk, setBulk] = useState('')
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState(null)
  const [err, setErr] = useState(null)
  const params = branch.length ? { branch: branch.join(',') } : {}
  const { data, isLoading, error } = useQuery({
    queryKey: ['batches', 'near-expiry', params],
    queryFn: () => batchesApi.nearExpiry(params).then(r => r.data),
  })
  const reload = () => { setTicked({}); qc.invalidateQueries({ queryKey: ['batches'] }) }
  const fail = e => setErr(e.response?.data?.detail || 'تعذّر الحفظ')
  const done = text => { setErr(null); setMsg(text); reload() }

  const choose = useMutation({
    mutationFn: ({ lots, action, note: n }) => batchesApi.nearExpiryChoose({ lots, action, note: n }).then(r => r.data),
    onSuccess: d => done(`سُجّل ${d.created} إجراء جديد · عُدّل ${d.updated}${d.skipped ? ` · تُخطّي ${d.skipped}` : ''}`),
    onError: fail,
  })
  const ret = useMutation({
    mutationFn: lots => batchesApi.nearExpiryRequestReturn(lots).then(r => r.data),
    onSuccess: d => done(`طلبات مرتجع جديدة ${d.created} · مربوطة ${d.linked}`),
    onError: fail,
  })
  const move = useMutation({
    mutationFn: async (r) => {
      let id = r.open_transfer?.id
      if (!id) {
        const m = r.detail.move[0]
        const res = await transfersApi.create({
          requesting_branch: m.to_id, supplying_branch: r.source_branch_id,
          notes: `إنقاذ قبل انتهاء الصلاحية — ${r.item_name} تشغيلة ${r.batch_no || '—'} تنتهي ${r.expiry_date}`,
          items: [{ item: r.item_id, quantity: Math.floor(m.qty) }],
        })
        id = res.data?.id
      }
      return batchesApi.nearExpiryLinkTransfer({ key: r.key, transfer_id: id })
    },
    onSuccess: () => done('رُبط طلب التحويل بالتشغيلة.'),
    onError: fail,
  })

  const filtered = useMemo(() => {
    const all = data?.rows || []
    return actionF ? all.filter(r => r.suggested_action === actionF) : all
  }, [data, actionF])
  const { sorted: rows, headerProps: h } = useSortableRows(filtered, { getValue: rowVal })
  const canChoose = !!data?.can_choose
  const accept = (r) => {
    if (!canChoose) return
    if (r.suggested_action === 'return') ret.mutate([r.key])
    else if (r.suggested_action !== 'accept_loss') choose.mutate({ lots: [r.key], action: r.suggested_action, note: '' })
  }
  const kb = useGridKeyboard({
    rows, getKey: r => r.key,
    onToggle: r => canChoose && setTicked(t => ({ ...t, [r.key]: !t[r.key] })),
    onSelectAll: () => canChoose && setTicked(Object.fromEntries(rows.map(r => [r.key, true]))),
    onConfirm: accept,
  })
  const tickedKeys = rows.filter(r => ticked[r.key]).map(r => r.key)
  const tickedReturns = rows.filter(r => ticked[r.key] && r.detail?.return).map(r => r.key)
  const branchOpts = (data?.branches || []).map(b => ({ code: b.code, name: bl(b.code) }))

  if (error) return <div className="text-red-600 text-sm">{error.response?.data?.detail || 'تعذّر التحميل'}</div>
  return (
    <div dir="rtl">
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4 text-sm text-blue-900 leading-relaxed">
        تشغيلات <b>لن تُباع قبل انتهائها</b> بمعدل بيع فرعها (الأقدم صلاحية أولاً)، مرتبة بالقيمة المعرّضة، ولكل تشغيلة
        إجراء مقترح واحد بالترتيب: مرتجع للمورد ← نقل لفرع يبيعه ← ركن «بيع أولاً» ← قبول الخسارة.
        أنت تختار الإجراء، وبعد {data?.settings?.outcome_days ?? 30} يوماً تظهر النتيجة في «ماذا حدث؟».
        «بيع أولاً» علامة على الرف فقط — <b>لا يتغير أي سعر</b>، ولا شيء يُكتب في SOFTECH.
      </div>
      <div className="mb-3"><DataFreshnessBar domains={['expiry', 'stock_audit']} /></div>

      <div className="flex flex-wrap items-center gap-2 mb-3 text-sm">
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          <button data-tour="batches-main-near-expiry-list" onClick={() => setView('list')}
                  className={`px-3 py-1 rounded-md ${view === 'list' ? 'bg-white shadow text-gray-900' : 'text-gray-500'}`}>🧭 قائمة العمل</button>
          <button data-tour="batches-main-near-expiry-outcomes" onClick={() => setView('outcomes')}
                  className={`px-3 py-1 rounded-md ${view === 'outcomes' ? 'bg-white shadow text-gray-900' : 'text-gray-500'}`}>📊 ماذا حدث؟</button>
        </div>
        {!data?.branch_only && (
          <MultiSelectFilter className="w-48" options={branchOpts} selected={branch} onChange={setBranch}
                             allLabel="كل الفروع" showCode={false} />
        )}
        <SavedViewsMenu sv={sv} />
        {view === 'outcomes' && data?.can_check_outcomes && (
          <button data-tour="batches-main-near-expiry-check" onClick={() => batchesApi.nearExpiryCheckOutcomes()
            .then(r => done(`قيست ${r.data.closed} نتيجة`)).catch(fail)}
                  className="px-3 py-1.5 bg-white border border-gray-300 rounded-lg hover:bg-gray-50">🔄 قياس النتائج الآن</button>
        )}
      </div>
      {msg && <p className="text-emerald-700 text-sm mb-2">{msg}</p>}
      {err && <p className="text-red-600 text-sm mb-2">{err}</p>}

      {view === 'outcomes' ? <Outcomes branch={branch} /> : (
        <>
          {data && !data.have_rates && (
            <div className="text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm mb-3">معدلات البيع غير متاحة — شغّل محرك الطلب أولاً.</div>
          )}
          {data?.pilot?.length > 0 && (
            <p className="text-xs text-gray-500 mb-2">فروع التجربة: {data.pilot.map(c => bl(c)).join('، ')}</p>
          )}
          <div data-tour="batches-main-near-expiry-chips" className="flex flex-wrap gap-2 mb-3">
            {ACTIONS.map(a => {
              const t = data?.totals?.[a.key] || { lines: 0, value: 0 }
              return (
                <button key={a.key} onClick={() => setActionF(f => (f === a.key ? '' : a.key))}
                        className={`px-3 py-1.5 rounded-xl text-sm border ${actionF === a.key ? 'ring-2 ring-primary' : ''} ${a.cls}`}>
                  {a.label}: <b>{fmtNum(t.value)} ج</b> · {t.lines}
                </button>
              )
            })}
          </div>

          {canChoose && (
            <div className="flex flex-wrap items-center gap-2 mb-2 text-sm">
              <select data-tour="batches-main-near-expiry-bulk" value={bulk} onChange={e => setBulk(e.target.value)} className="border rounded-lg px-2 py-1.5">
                <option value="">الإجراء للمحدد…</option>
                {ACTIONS.filter(a => a.key !== 'return').map(a => <option key={a.key} value={a.key}>{a.label}</option>)}
              </select>
              <input value={note} onChange={e => setNote(e.target.value)} placeholder={bulk === 'accept_loss' ? 'السبب (مطلوب)' : 'ملاحظة'}
                     className="border rounded-lg px-2 py-1.5 w-56" />
              <button data-tour="batches-main-near-expiry-choose" onClick={() => choose.mutate({ lots: tickedKeys, action: bulk, note })}
                      disabled={!bulk || !tickedKeys.length || choose.isPending || (bulk === 'accept_loss' && !note.trim())}
                      className="px-4 py-1.5 bg-primary text-white rounded-lg disabled:opacity-40">تسجيل الإجراء ({tickedKeys.length})</button>
              <button data-tour="batches-main-near-expiry-return" onClick={() => ret.mutate(tickedReturns)}
                      disabled={!tickedReturns.length || ret.isPending}
                      className="px-4 py-1.5 bg-white border border-gray-300 rounded-lg disabled:opacity-40">طلب مرتجع ({tickedReturns.length})</button>
              <span className="text-xs text-gray-400">{GRID_KEYS_HINT.replace(' · M مطابقة', '')} (Enter = الإجراء المقترح)</span>
            </div>
          )}

          {isLoading ? <div className="text-center py-10 text-gray-400">جاري حساب القائمة…</div> : !rows.length ? (
            <div className="text-center py-14 text-gray-400">لا توجد تشغيلات معرّضة للانتهاء قبل البيع لهذا الاختيار.</div>
          ) : (
            <div data-tour="batches-main-near-expiry-grid" {...kb.containerProps}
                 className={`bg-white rounded-xl border border-gray-200 overflow-x-auto ${kb.containerProps.className}`}>
              <table className="w-full text-sm whitespace-nowrap">
                <thead><tr className="bg-gray-50 border-b text-gray-600">
                  <th className="px-2 py-2" />
                  <SortTh {...h('item', 'text')} className="px-2 py-2 text-right">الصنف</SortTh>
                  <SortTh {...h('branch_code', 'text')} className="px-2 py-2 text-right">الفرع</SortTh>
                  <SortTh {...h('expiry_date', 'date')} className="px-2 py-2 text-right">الصلاحية</SortTh>
                  <SortTh {...h('qty', 'number')} className="px-2 py-2 text-right">الكمية</SortTh>
                  <SortTh {...h('rate_month', 'number')} className="px-2 py-2 text-right">بيع/شهر</SortTh>
                  <SortTh {...h('at_risk_qty', 'number')} className="px-2 py-2 text-right">لن يُباع</SortTh>
                  <SortTh {...h('at_risk_value', 'number')} className="px-2 py-2 text-right">القيمة (تكلفة)</SortTh>
                  <SortTh {...h('suggested', 'text')} className="px-2 py-2 text-right">المقترح</SortTh>
                  <th className="px-2 py-2 text-right">التفاصيل</th>
                  <SortTh {...h('chosen', 'text')} className="px-2 py-2 text-right">المختار</SortTh>
                </tr></thead>
                <tbody>
                  {rows.map(r => {
                    const rp = kb.rowProps(r)
                    const splitTxt = Object.entries(r.split || {}).filter(([, q]) => q > 0).map(([k, q]) => `${ACTION_SHORT[k]} ${fmtNum(q)}`).join(' · ')
                    return (
                      <tr key={r.key} {...rp} className={`border-b border-gray-100 ${rp.className}`}>
                        <td className="px-2 py-1.5">
                          <input type="checkbox" disabled={!canChoose} checked={!!ticked[r.key]}
                                 onChange={() => setTicked(t => ({ ...t, [r.key]: !t[r.key] }))} />
                        </td>
                        <td className="px-2 py-1.5">{r.item_name}<div className="text-[11px] text-gray-400">{r.item_code} · {r.batch_no || '—'}</div>
                          <div className="flex gap-1">
                            {r.fridge && <span className="text-[11px] text-sky-700">❄️ ثلاجة</span>}
                            {r.safety.filter(f => f.severity !== 'info').map(f => (
                              <span key={f.code} className={`text-[11px] ${f.severity === 'block' ? 'text-red-600' : 'text-amber-700'}`}>⚠️ {f.label}</span>
                            ))}
                          </div>
                        </td>
                        <td className="px-2 py-1.5 text-xs">{bl(r.branch_code)}</td>
                        <td className="px-2 py-1.5">{r.expiry_date}<div className={`text-[11px] ${r.days_left < 60 ? 'text-red-600' : 'text-gray-400'}`}>{r.days_left} يوم</div></td>
                        <td className="px-2 py-1.5">{fmtNum(r.qty, 2)}</td>
                        <td className="px-2 py-1.5 text-gray-500">{fmtNum(r.rate_month, 1)}</td>
                        <td className="px-2 py-1.5 font-semibold">{fmtNum(r.at_risk_qty, 2)}</td>
                        <td className="px-2 py-1.5">{fmtNum(r.at_risk_value)}</td>
                        <td className="px-2 py-1.5">
                          <span className={`px-2 py-0.5 rounded-full text-xs ${ACTION_CLS[r.suggested_action]}`}>{r.suggested_label}</span>
                          {Object.keys(r.split || {}).length > 1 && <div className="text-[11px] text-gray-400">{splitTxt}</div>}
                        </td>
                        <td className="px-2 py-1.5"><Detail r={r} /></td>
                        <td className="px-2 py-1.5 text-xs">
                          {r.action ? (
                            <span><span className={`px-2 py-0.5 rounded-full ${ACTION_CLS[r.action.chosen_action]}`}>{ACTION_SHORT[r.action.chosen_action]}</span>
                              {r.action.transfer && <span className="text-gray-500"> {r.action.transfer}</span>}
                              {r.action.disposal_record_id && <span className="text-gray-500"> طلب #{r.action.disposal_record_id}</span>}
                            </span>
                          ) : <span className="text-gray-300">—</span>}
                          {r.detail?.move?.length > 0 && data.can_create_transfer && !r.action?.transfer && r.item_id && (
                            <button data-tour="batches-main-near-expiry-transfer" onClick={() => move.mutate(r)} disabled={move.isPending}
                                    className="mr-1 px-2 py-0.5 bg-brand-600 text-white rounded disabled:opacity-50">
                              {r.open_transfer ? `ربط ${r.open_transfer.number}` : 'مسودة تحويل'}
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
