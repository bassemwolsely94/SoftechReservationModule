/**
 * ReturnWindowTab — «📆 تقويم المرتجع» on /batches (P-29).
 *
 * Which supplier should take back which batch, and by when: window = expiry month −2 … +1 (per
 * supplier policy). Lines are branch shelves + HQ live stores + store 105; the supplier is matched
 * from the purchase-expiry entries (confidence chip on every line). Advisory only — the return
 * (doc 120) and any transfer to HQ are posted in SOFTECH; a doc 120 closes the line by itself.
 * The server decides scope, states, quantities and permissions; this screen shows them.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { batchesApi, supplyApi } from '../api/client'
import DataFreshnessBar from './DataFreshnessBar'
import ProgressBar from './ProgressBar'
import useBranchLabels from '../hooks/useBranchLabels'
import useGridKeyboard, { GRID_KEYS_HINT } from '../hooks/useGridKeyboard'

const fmtNum = (n, d = 0) => Number(n ?? 0).toLocaleString('en-US', { maximumFractionDigits: d })
const STATES = [
  { key: 'closes_this_month', label: 'تُغلق هذا الشهر', cls: 'bg-red-100 text-red-700' },
  { key: 'open',              label: 'داخل النافذة',    cls: 'bg-green-100 text-green-700' },
  { key: 'opens_next_month',  label: 'تفتح الشهر القادم', cls: 'bg-blue-100 text-blue-700' },
  { key: 'missed',            label: 'فاتت النافذة',    cls: 'bg-gray-200 text-gray-600' },
]
const STATE_CLS = Object.fromEntries(STATES.map(s => [s.key, s.cls]))
const CONF_CLS = { exact: 'bg-green-50 text-green-700', month: 'bg-amber-50 text-amber-700',
                   ambiguous: 'bg-orange-100 text-orange-700', none: 'bg-gray-100 text-gray-500' }
const LOC_LABEL = { shelf: 'رف فرع', hq: 'مخزن رئيسي', '105': 'مخزن 105' }
const ANSWERS = [{ v: 'accepted', l: 'مقبول' }, { v: 'partial', l: 'جزئي' }, { v: 'rejected', l: 'مرفوض' }]

function download(res, name) {
  const url = window.URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a'); a.href = url; a.download = name
  document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
}

function AnswerCell({ line, onSaved }) {
  const rec = line.record
  const [ans, setAns] = useState(rec?.answer || '')
  const [qty, setQty] = useState(rec?.accepted_qty ?? '')
  const [allowed, setAllowed] = useState(rec?.allowed_expiry || '')
  const [err, setErr] = useState(null)
  const save = useMutation({
    mutationFn: () => batchesApi.returnWindowAnswer(rec.id, { answer: ans, accepted_qty: qty || undefined,
                                                             allowed_expiry: allowed || undefined }),
    onSuccess: () => { setErr(null); onSaved() },
    onError: e => setErr(e.response?.data?.detail || 'تعذّر الحفظ'),
  })
  if (!rec) return <span className="text-gray-300">—</span>
  if (rec.status === 'done') return <span className="text-indigo-700 text-xs">✅ مُرتجع ({fmtNum(rec.returned_qty, 2)})</span>
  if (rec.status === 'cancelled') return <span className="text-red-500 text-xs">{rec.status_display}</span>
  return (
    <div className="flex items-center gap-1">
      <select value={ans} onChange={e => setAns(e.target.value)} className="border rounded px-1 py-0.5 text-xs">
        <option value="">رد المورد…</option>
        {ANSWERS.map(a => <option key={a.v} value={a.v}>{a.l}</option>)}
      </select>
      {ans === 'partial' && (
        <input type="number" min="0" step="1" value={qty} onChange={e => setQty(e.target.value)}
               placeholder="كمية" className="border rounded px-1 py-0.5 text-xs w-16" />
      )}
      {(ans === 'accepted' || ans === 'partial') && (
        <input type="date" value={allowed} onChange={e => setAllowed(e.target.value)}
               title="الصلاحية المسموحة" className="border rounded px-1 py-0.5 text-xs" />
      )}
      <button disabled={!ans || save.isPending} onClick={() => save.mutate()}
              className="px-2 py-0.5 text-xs bg-primary text-white rounded disabled:opacity-40">حفظ</button>
      {rec.returned_qty > 0 && <span className="text-xs text-indigo-600">مُرتجع {fmtNum(rec.returned_qty, 2)}</span>}
      {err && <span className="text-xs text-red-600">{err}</span>}
    </div>
  )
}

function PolicyTable({ canEdit }) {
  const qc = useQueryClient()
  const { data } = useQuery({ queryKey: ['batches', 'return-policies'],
                              queryFn: () => batchesApi.returnWindowPolicies().then(r => r.data) })
  const [edit, setEdit] = useState(null)
  const [err, setErr] = useState(null)
  const save = useMutation({
    mutationFn: (body) => batchesApi.returnWindowSavePolicy(body),
    onSuccess: () => { setEdit(null); setErr(null); qc.invalidateQueries({ queryKey: ['batches'] }) },
    onError: e => setErr(e.response?.data?.detail || 'تعذّر الحفظ'),
  })
  const rows = data?.policies || []
  const field = (k, v) => setEdit(e => ({ ...e, [k]: v }))
  return (
    <div data-tour="batches-main-return-policies" className="bg-white rounded-xl border border-gray-200 p-4 mt-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-bold text-gray-800">سياسات مرتجع الموردين</h3>
        {canEdit && !edit && (
          <button onClick={() => setEdit({ supplier_code: '', supplier_name: '', accepts_expiry_returns: true,
                                           open_offset: -2, close_offset: 1, self_entry: false, notes: '', isNew: true })}
                  className="px-3 py-1 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">+ مورد</button>
        )}
      </div>
      <table className="w-full text-sm">
        <thead><tr className="text-gray-500 text-xs border-b">
          <th className="text-right py-2">المورد</th><th className="text-right">يقبل مرتجع الصلاحية</th>
          <th className="text-right">تفتح (شهور)</th><th className="text-right">تُغلق (شهور)</th>
          <th className="text-right">إدخال في نظام المورد</th><th className="text-right">ملاحظات</th><th />
        </tr></thead>
        <tbody>
          {[...rows, ...(edit?.isNew ? [edit] : [])].map(p => {
            const on = edit && edit.supplier_code === p.supplier_code && (edit.isNew === p.isNew)
            const v = on ? edit : p
            return (
              <tr key={p.isNew ? 'new' : p.supplier_code} className="border-b border-gray-100">
                <td className="py-2">
                  {on && p.isNew
                    ? <input value={v.supplier_code} onChange={e => field('supplier_code', e.target.value)}
                             placeholder="كود المورد" className="border rounded px-1 w-24" />
                    : <span>{p.supplier_code} · {p.supplier_name}</span>}
                </td>
                <td>{on ? <input type="checkbox" checked={!!v.accepts_expiry_returns}
                                  onChange={e => field('accepts_expiry_returns', e.target.checked)} />
                         : (p.accepts_expiry_returns ? '✓' : '✗')}</td>
                <td>{on ? <input type="number" max="0" min="-12" step="1" value={v.open_offset}
                                  onChange={e => field('open_offset', e.target.value)} className="border rounded px-1 w-16" />
                         : p.open_offset}</td>
                <td>{on ? <input type="number" min="0" max="12" step="1" value={v.close_offset}
                                  onChange={e => field('close_offset', e.target.value)} className="border rounded px-1 w-16" />
                         : `+${p.close_offset}`}</td>
                <td>{on ? <input type="checkbox" checked={!!v.self_entry}
                                  onChange={e => field('self_entry', e.target.checked)} />
                         : (p.self_entry ? '✓' : '—')}</td>
                <td>{on ? <input value={v.notes || ''} onChange={e => field('notes', e.target.value)}
                                  className="border rounded px-1 w-48" />
                         : <span className="text-gray-500 text-xs">{p.notes}</span>}</td>
                <td className="text-left">
                  {on ? (
                    <span className="flex gap-1 justify-end">
                      <button onClick={() => save.mutate(edit)} disabled={save.isPending || !edit.supplier_code}
                              className="px-2 py-0.5 text-xs bg-primary text-white rounded disabled:opacity-40">حفظ</button>
                      <button onClick={() => { setEdit(null); setErr(null) }} className="px-2 py-0.5 text-xs border rounded">إلغاء</button>
                    </span>
                  ) : canEdit && !edit && (
                    <button onClick={() => setEdit({ ...p })} className="px-2 py-0.5 text-xs border rounded">تعديل</button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {err && <p className="text-sm text-red-600 mt-2">{err}</p>}
    </div>
  )
}

export default function ReturnWindowTab() {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [supplier, setSupplier] = useState('')
  const [location, setLocation] = useState('')
  const [stateF, setStateF] = useState('')
  const [ticked, setTicked] = useState({})
  const [pick, setPick] = useState({})               // line key → chosen supplier (ambiguous lines)
  const [msg, setMsg] = useState(null)
  const [since, setSince] = useState(null)

  const params = { month, supplier: supplier || undefined, location: location || undefined }
  const { data, isLoading } = useQuery({
    queryKey: ['batches', 'return-window', params],
    queryFn: () => batchesApi.returnWindow(params).then(r => r.data),
  })
  const allLines = data?.lines || []
  const lines = useMemo(() => allLines.filter(l => !stateF || l.state === stateF), [allLines, stateF])
  const reload = () => qc.invalidateQueries({ queryKey: ['batches', 'return-window'] })
  const supplierOf = (l) => l.supplier_code || pick[l.key] || ''

  const request = useMutation({
    mutationFn: (rows) => batchesApi.returnWindowRequest(rows.map(l => ({
      branch_code: l.branch_code, store_code: l.store_code, item_code: l.item_code, batch_no: l.batch_no,
      expiry_date: l.expiry_date, supplier_code: supplierOf(l) }))),
    onSuccess: (r) => { setMsg(r.data.detail); setTicked({}); reload() },
    onError: e => setMsg(e.response?.data?.detail || 'تعذّر إنشاء الطلب'),
  })
  const answerAccepted = useMutation({
    mutationFn: (l) => batchesApi.returnWindowAnswer(l.record.id, { answer: 'accepted' }),
    onSuccess: reload,
  })
  const exportX = useMutation({
    mutationFn: (kind) => batchesApi.returnWindowExport({ kind, supplier_code: supplier || undefined, month,
                                                          location: location || undefined }),
    onSuccess: (res, kind) => download(res, kind === 'supplier' ? `return_${supplier}.xlsx` : 'return_window.xlsx'),
    onError: () => setMsg('تعذّر التصدير — اختر المورد أولاً لملف المورد.'),
  })
  const refresh = useMutation({
    mutationFn: async (what) => {
      setSince(Date.now())
      if (what === 'expiry') return batchesApi.stockExpirySync({})
      if (what === 'purchase_expiry') {
        const to = new Date(); const from = new Date(Date.now() - 45 * 86400000)
        return batchesApi.purchaseExpirySync({ from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) })
      }
      if (what === 'purchases') return supplyApi.refreshPurchases()
      return batchesApi.returnWindowReconcile()
    },
    onSuccess: (r, what) => {
      setSince(null)
      setMsg(what === 'reconcile'
        ? `مطابقة مستندات المرتجع: أُغلق ${r.data.closed} · جزئي ${r.data.partial}`
        : (r.data?.detail || 'بدأ التحديث في الخلفية.'))
      reload(); qc.invalidateQueries({ queryKey: ['data-freshness'] })
    },
    onError: e => { setSince(null); setMsg(e.response?.data?.detail || 'تعذّر التحديث') },
  })

  const canTick = (l) => data?.can_request && !l.record && !!supplierOf(l) && l.state !== 'missed'
  const kb = useGridKeyboard({
    rows: lines, getKey: l => l.key,
    onToggle: (l) => canTick(l) && setTicked(t => ({ ...t, [l.key]: !t[l.key] })),
    onSelectAll: () => setTicked(Object.fromEntries(lines.filter(canTick).map(l => [l.key, true]))),
    onConfirm: (l) => l.record && !l.record.answer && l.record.status === 'draft' && answerAccepted.mutate(l),
  })
  const tickedRows = lines.filter(l => ticked[l.key])
  const suppliers = Object.entries(data?.suppliers || {})

  return (
    <div>
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4 text-sm text-blue-900 leading-relaxed">
        نافذة المرتجع = من شهرين قبل شهر الانتهاء حتى شهر بعده (حسب سياسة كل مورد). المورد مستنتج من فواتير الشراء
        (انظر «الثقة»). النظام <b>لا يُنشئ مستند مرتجع</b> — يُدخل المرتجع في SOFTECH (مستند 120) فيُغلق السطر تلقائياً.
        {data?.branch_only && <> سطور فرعك: <b>أرسلها للرئيسي قبل التاريخ المذكور</b>.</>}
      </div>

      <div className="mb-3">
        <DataFreshnessBar domains={['expiry', 'purchase_expiry', 'purchases']} />
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-3 text-sm">
        <input type="month" value={month} onChange={e => setMonth(e.target.value)} className="border rounded-lg px-2 py-1.5" />
        <select value={supplier} onChange={e => setSupplier(e.target.value)} className="border rounded-lg px-2 py-1.5">
          <option value="">كل الموردين</option>
          {suppliers.map(([code, s]) => <option key={code} value={code}>{code} · {s.supplier_name}</option>)}
        </select>
        <select value={location} onChange={e => setLocation(e.target.value)} className="border rounded-lg px-2 py-1.5">
          <option value="">كل المواقع</option>
          <option value="shelf">رفوف الفروع</option>
          <option value="hq">مخازن الرئيسي</option>
          <option value="105">مخزن 105</option>
        </select>
        {stateF && <button onClick={() => setStateF('')} className="px-2 py-1 text-xs border rounded-lg">✕ {STATES.find(s => s.key === stateF)?.label}</button>}
        <span className="flex-1" />
        <button onClick={() => refresh.mutate('expiry')} disabled={refresh.isPending} className="px-3 py-1.5 border rounded-lg hover:bg-gray-50 disabled:opacity-50">🔄 أرصدة الصلاحية</button>
        <button onClick={() => refresh.mutate('purchase_expiry')} disabled={refresh.isPending} className="px-3 py-1.5 border rounded-lg hover:bg-gray-50 disabled:opacity-50">🔄 صلاحيات الشراء</button>
        <button onClick={() => refresh.mutate('purchases')} disabled={refresh.isPending} className="px-3 py-1.5 border rounded-lg hover:bg-gray-50 disabled:opacity-50">🔄 المشتريات والمرتجعات</button>
        <button onClick={() => refresh.mutate('reconcile')} disabled={refresh.isPending} className="px-3 py-1.5 border rounded-lg hover:bg-gray-50 disabled:opacity-50">↩️ مطابقة مستندات المرتجع</button>
      </div>
      {refresh.isPending && <ProgressBar label="تحديث" message="جارٍ التحديث…" since={since} className="mb-3" />}
      {msg && <div className="mb-3 text-sm text-gray-700 bg-gray-50 border rounded-lg px-3 py-2">{msg}</div>}

      {/* Per-supplier summary: click a value to filter the grid */}
      <div data-tour="batches-main-return-summary" className="grid gap-2 mb-4">
        {suppliers.map(([code, s]) => (
          <div key={code} className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex flex-wrap items-center gap-3 text-sm">
            <b className="min-w-40">{code} · {s.supplier_name}</b>
            {STATES.map(st => (
              <button key={st.key} onClick={() => { setSupplier(code); setStateF(st.key) }}
                      className={`px-2 py-1 rounded-lg ${st.cls} hover:opacity-80`}>
                {st.label}: <b>{fmtNum(s[st.key]?.value)} ج</b>
              </button>
            ))}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-2 text-sm">
        <button data-tour="batches-main-return-request" onClick={() => request.mutate(tickedRows)}
                disabled={!tickedRows.length || request.isPending}
                className="px-4 py-2 bg-primary text-white rounded-lg disabled:opacity-40">طلب مرتجع ({tickedRows.length})</button>
        <button data-tour="batches-main-return-export" onClick={() => exportX.mutate('supplier')} disabled={!supplier || exportX.isPending}
                title={supplier ? '' : 'اختر المورد أولاً'}
                className="px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40">⬇️ تصدير للمورد</button>
        <button onClick={() => exportX.mutate('grid')} disabled={!lines.length || exportX.isPending}
                className="px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40">⬇️ تصدير Excel</button>
        <span className="text-xs text-gray-400">{GRID_KEYS_HINT.replace(' · M مطابقة', '')} (Enter = مقبول)</span>
      </div>

      {isLoading ? <div className="text-center py-10 text-gray-400">جارٍ التحميل…</div> : lines.length === 0 ? (
        <div className="text-center py-14 text-gray-400">لا توجد سطور في نوافذ المرتجع لهذا الاختيار.</div>
      ) : (
        <div data-tour="batches-main-return-grid" {...kb.containerProps}
             className={`bg-white rounded-xl border border-gray-200 overflow-x-auto ${kb.containerProps.className}`}>
          <table className="w-full text-sm whitespace-nowrap">
            <thead><tr className="bg-gray-50 border-b border-gray-200 text-gray-600">
              <th className="px-2 py-2" /><th className="px-2 py-2 text-right">الصنف</th>
              <th className="px-2 py-2 text-right">الموقع</th><th className="px-2 py-2 text-right">التشغيلة</th>
              <th className="px-2 py-2 text-right">الصلاحية</th><th className="px-2 py-2 text-right">الكمية</th>
              <th className="px-2 py-2 text-right">القيمة</th><th className="px-2 py-2 text-right">تُغلق</th>
              <th className="px-2 py-2 text-right">الحالة</th><th className="px-2 py-2 text-right">المورد / الثقة</th>
              <th className="px-2 py-2 text-right">سابقاً</th><th className="px-2 py-2 text-right">الطلب / رد المورد</th>
            </tr></thead>
            <tbody>
              {lines.map(l => {
                const rp = kb.rowProps(l)
                return (
                  <tr key={l.key} {...rp} className={`border-b border-gray-100 ${rp.className}`}>
                    <td className="px-2 py-2">
                      <input type="checkbox" disabled={!canTick(l)} checked={!!ticked[l.key]}
                             onChange={() => setTicked(t => ({ ...t, [l.key]: !t[l.key] }))} />
                    </td>
                    <td className="px-2 py-2 font-medium">{l.item_name || l.item_code}<span className="text-xs text-gray-400"> {l.item_code}</span></td>
                    <td className="px-2 py-2 text-xs">{bl(l.branch_code)} · {LOC_LABEL[l.location]}</td>
                    <td className="px-2 py-2 text-xs text-gray-500">{l.batch_no || '—'}</td>
                    <td className="px-2 py-2">{l.expiry_date}</td>
                    <td className="px-2 py-2">{fmtNum(l.qty, 2)}</td>
                    <td className="px-2 py-2">{fmtNum(l.value)}</td>
                    <td className="px-2 py-2">
                      {l.closes}
                      {l.send_by && <div className="text-xs text-red-600">أرسل للرئيسي قبل {l.send_by}</div>}
                    </td>
                    <td className="px-2 py-2"><span className={`px-2 py-0.5 rounded-full text-xs ${STATE_CLS[l.state]}`}>{l.state_label}</span></td>
                    <td className="px-2 py-2 text-xs">
                      {l.confidence === 'ambiguous' && !l.record ? (
                        <select value={pick[l.key] || ''} onChange={e => setPick(p => ({ ...p, [l.key]: e.target.value }))}
                                className="border rounded px-1 py-0.5">
                          <option value="">اختر المورد…</option>
                          {l.candidates.map(c => <option key={c.code} value={c.code}>{c.code} · {c.name}</option>)}
                        </select>
                      ) : <span>{l.supplier_name || l.supplier_code || '—'}</span>}
                      {' '}<span className={`px-1.5 py-0.5 rounded ${CONF_CLS[l.confidence]}`}>{l.confidence_label}</span>
                    </td>
                    <td className="px-2 py-2 text-xs text-gray-500">{l.history || '—'}</td>
                    <td className="px-2 py-2"><AnswerCell line={l} onSaved={reload} /></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {data?.no_policy?.length > 0 && (
        <div data-tour="batches-main-return-nopolicy" className="bg-amber-50 border border-amber-200 rounded-xl p-4 mt-6 text-sm">
          <h3 className="font-bold text-amber-900 mb-2">موردون بدون سياسة مرتجع (قيمة داخل النافذة)</h3>
          <div className="flex flex-wrap gap-2">
            {data.no_policy.map(r => (
              <span key={r.supplier_code || 'unknown'} className="px-2 py-1 bg-white border border-amber-200 rounded-lg">
                {r.supplier_code ? `${r.supplier_code} · ` : ''}{r.supplier_name}: <b>{fmtNum(r.value)} ج</b>
              </span>
            ))}
          </div>
          <p className="text-xs text-amber-800 mt-2">أدخل سياسة المورد في الجدول أدناه ليظهر في التقويم.</p>
        </div>
      )}

      <PolicyTable canEdit={!!data?.can_edit_policy} />
    </div>
  )
}
