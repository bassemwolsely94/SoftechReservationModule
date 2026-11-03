/**
 * InsuranceReportsPage — «تقارير المطالبات»: dashboard + reports over every motalba whose
 * claim period overlaps the chosen dates. All numbers come from the backend
 * (apps/insurance/portfolio.py); this page only displays, sorts, orders and exports.
 */
import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'
import useBranchLabels from '../hooks/useBranchLabels'
import useSortableRows from '../hooks/useSortableRows'
import { nextSort, sortRows, ariaSortOf } from '../hooks/sortCompare'
import SortTh from '../components/SortTh'

const inp = 'border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500'
const n0 = (v) => Number(v || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const n2 = (v) => Number(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pct = (v) => `${Number(v || 0).toFixed(1)}%`
const STATUS = { draft: 'مسودة', ready: 'جاهزة', submitted: 'مُقدَّمة', under_review: 'قيد المراجعة',
  partially_paid: 'مدفوعة جزئياً', paid: 'مدفوعة', rejected: 'مرفوضة', cancelled: 'ملغاة' }
const TABS = [
  ['dashboard', 'لوحة المؤشرات'], ['motalbas', 'المطالبات'], ['bridge', 'جسر القيمة'], ['branches', 'الفروع'],
  ['claim_branch', 'المطالبة × الفرع'], ['sellers', 'البائعون'], ['categories', 'الفئات المالية'],
  ['moves', 'تحويلات بين المطالبات'],
]

function monthStart() { const d = new Date(); d.setMonth(d.getMonth() - 1); d.setDate(1); return d.toISOString().slice(0, 10) }
function monthEnd() { const d = new Date(); d.setDate(0); return d.toISOString().slice(0, 10) }

// a sortable table over plain rows; cols = [key, label, kind(text|int|money|pct), total?]
function Grid({ rows, cols, initial, tour, total = true }) {
  const kindOf = Object.fromEntries(cols.map(([k, , kind]) => [k, kind === 'text' ? 'text' : 'number']))
  const first = initial || cols[0][0]
  const { sorted, headerProps } = useSortableRows(rows, { defaultSort: { key: first, dir: 'desc', type: kindOf[first] || 'number' } })
  const fmt = (v, kind) => kind === 'money' ? n2(v) : kind === 'int' ? n0(v) : kind === 'pct' ? pct(v) : (v ?? '—')
  const sums = cols.filter(c => c[2] === 'money' || c[2] === 'int')
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-auto max-h-[calc(100vh-330px)]" data-tour={tour}>
      <table className="w-full text-xs">
        <thead className="bg-gray-50 text-gray-500 sticky top-0 z-10"><tr>
          {cols.map(([k, l, kind]) => (
            <SortTh key={k} {...headerProps(k, kindOf[k])}
              className={`px-2 py-2 font-semibold whitespace-nowrap ${kind === 'text' ? 'text-right' : 'text-left'}`}>{l}</SortTh>
          ))}</tr></thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map((r, i) => (
            <tr key={i} className="hover:bg-gray-50">
              {cols.map(([k, , kind]) => (
                <td key={k} className={`px-2 py-1.5 whitespace-nowrap ${kind === 'text' ? 'text-right text-gray-800' : 'text-left font-mono'}`}>{fmt(r[k], kind)}</td>
              ))}
            </tr>
          ))}
          {total && rows.length > 0 && (
            <tr className="bg-green-50 font-bold">
              {cols.map(([k, , kind], i) => (
                <td key={k} className={`px-2 py-1.5 ${kind === 'text' ? 'text-right' : 'text-left font-mono'}`}>
                  {i === 0 ? 'الإجمالى' : sums.some(s => s[0] === k) ? fmt(rows.reduce((s, r) => s + Number(r[k] || 0), 0), kind) : ''}
                </td>
              ))}
            </tr>
          )}
          {!rows.length && <tr><td colSpan={cols.length} className="px-3 py-8 text-center text-gray-400">لا بيانات.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

function Bars({ rows, label, value, fmtV = n0 }) {
  const max = Math.max(1, ...rows.map(r => Number(r[value] || 0)))
  return (
    <div className="space-y-1">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <span className="w-40 truncate text-gray-600" title={r[label]}>{r[label]}</span>
          <div className="flex-1 bg-gray-100 rounded h-3">
            <div className="bg-blue-500 h-3 rounded" style={{ width: `${Math.max(1, (Number(r[value] || 0) / max) * 100)}%` }} />
          </div>
          <span className="w-24 text-left font-mono text-gray-700">{fmtV(r[value])}</span>
        </div>
      ))}
    </div>
  )
}

export default function InsuranceReportsPage() {
  const navigate = useNavigate()
  const bl = useBranchLabels()
  const [clients, setClients] = useState([])
  const [subs, setSubs]       = useState([])
  const [f, setF] = useState({ from: monthStart(), to: monthEnd(), client_id: '', subclient_id: '', status: '' })
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState(null)
  const [tab, setTab]         = useState('dashboard')
  const [order, setOrder]     = useState([])      // custom motalba order (claim ids)
  const [groupByClient, setGroupByClient] = useState(false)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    Promise.all([insuranceApi.clients(), insuranceApi.subclients()]).then(([c, s]) => {
      setClients(c.data.results || c.data); setSubs(s.data.results || s.data)
    }).catch(() => {})
  }, [])
  const params = () => ({ from: f.from || undefined, to: f.to || undefined, client_id: f.client_id || undefined,
    subclient_id: f.subclient_id || undefined, status: f.status || undefined })
  const load = () => {
    setLoading(true); setErr(null)
    insuranceApi.portfolio(params())
      .then(r => { setData(r.data); setOrd(null); setOrder(r.data.motalbas.map(m => m.claim_id)) })
      .catch(e => setErr(e.response?.data?.detail || 'تعذّر تحميل التقرير'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])   // eslint-disable-line

  const ordered = useMemo(() => {
    if (!data) return []
    const pos = Object.fromEntries(order.map((id, i) => [id, i]))
    return [...data.motalbas].sort((a, b) => (pos[a.claim_id] ?? 1e9) - (pos[b.claim_id] ?? 1e9))
  }, [data, order])
  const move = (id, d) => { setOrd(null); setOrder(o => {
    const i = o.indexOf(id), j = i + d
    if (i < 0 || j < 0 || j >= o.length) return o
    const n = [...o]; [n[i], n[j]] = [n[j], n[i]]; return n
  }) }
  // header clicks and the quick buttons both re-order the motalbas (and so the export); a third click restores the server order
  const [ord, setOrd] = useState(null)
  const applyOrd = (next) => {
    setOrd(next)
    setOrder((next ? sortRows(data?.motalbas || [], next, (m, k) => m[k]) : (data?.motalbas || [])).map(m => m.claim_id))
  }
  const sortOrder = (k, dir = 'desc', type = 'text') => applyOrd({ key: k, dir, type, step: 1 })
  const orderHead = (key, type = 'text') => {
    const active = ord?.key === key
    return { active, dir: active ? ord.dir : undefined, ariaSort: ariaSortOf(active, ord?.dir), onSort: () => applyOrd(nextSort(ord, key, type)) }
  }

  const exportXlsx = async () => {
    setExporting(true)
    try {
      const { data: blob } = await insuranceApi.portfolioExport({ ...params(), order: order.join(','),
        group_by_client: groupByClient ? 1 : undefined })
      const url = URL.createObjectURL(new Blob([blob], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }))
      const a = document.createElement('a'); a.href = url; a.download = `تقارير_المطالبات_${f.from}_${f.to}.xlsx`
      document.body.appendChild(a); a.click(); document.body.removeChild(a)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch { setErr('تعذّر التصدير') } finally { setExporting(false) }
  }

  const T = data?.totals || {}
  const bridgeRows = ordered.map(m => ({ claim_number: m.claim_number, client: m.client, ...Object.fromEntries(
    Object.entries(m.bridge).map(([k, v]) => [`b_${k}`, v])) }))
  const card = (label, value, sub, cls = 'text-gray-900') => (
    <div className="bg-white border border-gray-200 rounded-xl p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-bold font-mono ${cls}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-400">{sub}</div>}
    </div>
  )

  return (
    <div className="p-6 space-y-4" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <button onClick={() => navigate('/insurance')} className="text-sm text-blue-600 hover:underline">← مطالبات التأمين</button>
          <h1 className="text-xl font-bold text-gray-800 mt-1">تقارير المطالبات</h1>
          <p className="text-xs text-gray-500">كل مطالبة تتقاطع فترتها مع التواريخ المختارة. التكلفة والبائع من سطور البيع فى سوفتك وقت البيع؛ الإيراد = صافى المطالبة + نصيب المريض. للعرض فقط.</p>
        </div>
        <button onClick={exportXlsx} disabled={!data || exporting} data-tour="insurance-reports-export"
          className="px-4 py-2 bg-green-600 text-white text-sm rounded-lg disabled:opacity-40">{exporting ? 'جارٍ التصدير…' : '📥 تصدير Excel (كل التقارير)'}</button>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl p-3 flex flex-wrap items-end gap-2" data-tour="insurance-reports-filters">
        <label className="text-xs text-gray-500">من<input type="date" className={`${inp} block mt-0.5`} value={f.from} onChange={e => setF({ ...f, from: e.target.value })} /></label>
        <label className="text-xs text-gray-500">إلى<input type="date" className={`${inp} block mt-0.5`} value={f.to} onChange={e => setF({ ...f, to: e.target.value })} /></label>
        <label className="text-xs text-gray-500">الجهة
          <select className={`${inp} block mt-0.5 max-w-[260px]`} value={f.client_id} onChange={e => setF({ ...f, client_id: e.target.value, subclient_id: '' })}>
            <option value="">كل الجهات</option>
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}{(() => { const s = subs.filter(x => x.client === c.id).map(x => x.name).join('، '); return s ? ` — ${s}` : '' })()}</option>)}
          </select></label>
        <label className="text-xs text-gray-500">الفئة
          <select className={`${inp} block mt-0.5`} value={f.subclient_id} disabled={!f.client_id} onChange={e => setF({ ...f, subclient_id: e.target.value })}>
            <option value="">كل الفئات</option>
            {subs.filter(s => String(s.client) === String(f.client_id)).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select></label>
        <label className="text-xs text-gray-500">الحالة
          <select className={`${inp} block mt-0.5`} value={f.status} onChange={e => setF({ ...f, status: e.target.value })}>
            <option value="">كل الحالات (عدا الملغاة والمرفوضة)</option>
            {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        <button onClick={load} disabled={loading} data-tour="insurance-reports-run" className="px-4 py-2 bg-blue-600 text-white text-sm rounded disabled:opacity-40">{loading ? 'جارٍ…' : 'عرض'}</button>
      </div>
      {err && <div className="text-sm text-red-600">{err}</div>}

      {data && (
        <>
          <div className="flex gap-1 flex-wrap border-b border-gray-200" data-tour="insurance-reports-tabs">
            {TABS.map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`px-3 py-2 text-sm border-b-2 -mb-px ${tab === k ? 'border-blue-600 text-blue-700 font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>{l}</button>
            ))}
          </div>

          {tab === 'dashboard' && (
            <div className="space-y-4" data-tour="insurance-reports-dashboard">
              <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
                {card('المطالبات', n0(T.motalbas), `${n0(T.rx_count)} روشتة · ${n0(T.patients)} مريض`)}
                {card('صافى المطالبات', n2(T.net), `قبل الخصم ${n2(T.gross)}`)}
                {card('الإيراد (المطالبة + المريض)', n2(T.revenue), `نصيب المريض ${n2(T.patient_share)}`)}
                {card('التكلفة', n2(T.cost), 'من سوفتك وقت البيع')}
                {card('مجمل الربح', n2(T.gp), pct(T.gp_pct), 'text-green-700')}
                {card('الرصيد', n2(T.balance), `المحصل ${n2(T.collected)}`, 'text-amber-700')}
                {card('محلى (صافى)', n2(T.local_net), `ربح ${n2(T.local_gp)}`)}
                {card('مستورد (صافى)', n2(T.imported_net), `ربح ${n2(T.imported_gp)}`)}
                {card('ترسية (صافى)', n2(T.tarsia_net), `ربح ${n2(T.tarsia_gp)}`)}
                {card('زيادة القيمة من تعديلات سوفتك', n2(T.bridge_softech_edits_delta), `${n0(T.bridge_softech_edits)} إيصال`, 'text-blue-700')}
                {card('إضافات من مطالبات أخرى', n2(T.bridge_from_other_net), `${n0(T.bridge_from_other_count)} روشتة`, 'text-blue-700')}
                {card('مستبعد', n2(T.bridge_excluded_net), `${n0(T.bridge_excluded_count)} روشتة`, 'text-red-600')}
              </div>
              <div className="grid md:grid-cols-2 gap-4">
                <div className="bg-white border border-gray-200 rounded-xl p-3"><div className="text-sm font-semibold mb-2">الفروع — الصافى</div>
                  <Bars rows={data.branches.slice(0, 12).map(b => ({ ...b, label: bl(b.branch) }))} label="label" value="net" /></div>
                <div className="bg-white border border-gray-200 rounded-xl p-3"><div className="text-sm font-semibold mb-2">الفروع — نسبة مجمل الربح</div>
                  <Bars rows={data.branches.slice(0, 12).map(b => ({ ...b, label: bl(b.branch) }))} label="label" value="gp_pct" fmtV={pct} /></div>
                <div className="bg-white border border-gray-200 rounded-xl p-3"><div className="text-sm font-semibold mb-2">أكبر المطالبات — الصافى</div>
                  <Bars rows={[...data.motalbas].sort((a, b) => b.net - a.net).slice(0, 12).map(m => ({ ...m, label: `${m.claim_number} · ${m.client}` }))} label="label" value="net" /></div>
                <div className="bg-white border border-gray-200 rounded-xl p-3"><div className="text-sm font-semibold mb-2">الشهور — مجمل الربح</div>
                  <Bars rows={data.trend} label="month" value="gp" /></div>
              </div>
            </div>
          )}

          {tab === 'motalbas' && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs" data-tour="insurance-reports-order">
                <span className="text-gray-500" title="الضغط على عنوان أى عمود فى الجدول يغيّر الترتيب ويغيّر ترتيب التصدير أيضاً">ترتيب المطالبات (يُطبَّق على التصدير — والضغط على عنوان عمود يغيّره أيضاً):</span>
                {[['period_from', 'الفترة', 'asc', 'date'], ['client', 'الجهة', 'asc'], ['net', 'الصافى', 'desc', 'number'], ['gp_pct', 'نسبة الربح', 'desc', 'number'], ['claim_number', 'الرقم', 'asc']].map(([k, l, d, t]) => (
                  <button key={k} onClick={() => sortOrder(k, d, t)} className="px-2 py-1 rounded border border-gray-300 bg-white hover:bg-gray-50">{l}</button>
                ))}
                <label className="flex items-center gap-1 mr-3"><input type="checkbox" checked={groupByClient} onChange={e => setGroupByClient(e.target.checked)} />
                  إجماليات فرعية لكل جهة فى التصدير</label>
              </div>
              <div className="bg-white rounded-xl border border-gray-200 overflow-auto max-h-[calc(100vh-360px)]" data-tour="insurance-reports-motalbas">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500 sticky top-0"><tr>
                    <th className="px-2 py-2" />
                    {[['claim_number', 'المطالبة'], ['client', 'الجهة'], ['subclient', 'الفئة'], ['period_from', 'الفترة', 'date'],
                      ['status', 'الحالة'], ['rx_count', 'روشتات', 'number'], ['local_before', 'محلى', 'number'],
                      ['imported_before', 'مستورد', 'number'], ['tarsia_before', 'ترسية', 'number'], ['gross', 'الإجمالى', 'number'],
                      ['discount', 'الخصم', 'number'], ['net', 'الصافى', 'number'], ['patient_share', 'نصيب المريض', 'number'],
                      ['cost', 'التكلفة', 'number'], ['gp', 'مجمل الربح', 'number'], ['gp_pct', 'GP%', 'number'],
                      ['local_gp_pct', 'محلى%', 'number'], ['imported_gp_pct', 'مستورد%', 'number'],
                      ['tarsia_gp_pct', 'ترسية%', 'number'], ['balance', 'الرصيد', 'number']].map(([k, l, t]) => (
                      <SortTh key={k} {...orderHead(k, t)} className="px-2 py-2 text-right whitespace-nowrap">{l}</SortTh>
                    ))}
                  </tr></thead>
                  <tbody className="divide-y divide-gray-100">
                    {ordered.map((m, i) => (
                      <tr key={m.claim_id} className="hover:bg-gray-50">
                        <td className="px-1 whitespace-nowrap"><button onClick={() => move(m.claim_id, -1)} disabled={i === 0} className="px-1 text-gray-400 disabled:opacity-20">▲</button>
                          <button onClick={() => move(m.claim_id, 1)} disabled={i === ordered.length - 1} className="px-1 text-gray-400 disabled:opacity-20">▼</button></td>
                        <td className="px-2 py-1.5 font-mono"><a className="text-blue-700 hover:underline" href={`/insurance/claims/${m.claim_id}`}>{m.claim_number}</a></td>
                        <td className="px-2 text-gray-800 max-w-[220px] truncate" title={m.client}>{m.client}</td>
                        <td className="px-2 text-gray-600">{m.subclient}</td>
                        <td className="px-2 font-mono text-gray-500 whitespace-nowrap">{m.period_from} ← {m.period_to}</td>
                        <td className="px-2">{STATUS[m.status] || m.status}</td>
                        <td className="px-2 text-left font-mono">{n0(m.rx_count)}</td>
                        {['local_before', 'imported_before', 'tarsia_before', 'gross', 'discount', 'net', 'patient_share', 'cost', 'gp'].map(k =>
                          <td key={k} className={`px-2 text-left font-mono ${k === 'gp' ? 'text-green-700 font-semibold' : ''}`}>{n2(m[k])}</td>)}
                        {['gp_pct', 'local_gp_pct', 'imported_gp_pct', 'tarsia_gp_pct'].map(k => <td key={k} className="px-2 text-left font-mono">{pct(m[k])}</td>)}
                        <td className="px-2 text-left font-mono text-amber-700">{n2(m.balance)}</td>
                      </tr>
                    ))}
                    <tr className="bg-green-50 font-bold">
                      <td /><td className="px-2 py-1.5" colSpan={5}>الإجمالى ({n0(T.motalbas)} مطالبة)</td>
                      <td className="px-2 text-left font-mono">{n0(T.rx_count)}</td>
                      {['local_before', 'imported_before', 'tarsia_before', 'gross', 'discount', 'net', 'patient_share', 'cost', 'gp'].map(k =>
                        <td key={k} className="px-2 text-left font-mono">{n2(T[k])}</td>)}
                      <td className="px-2 text-left font-mono">{pct(T.gp_pct)}</td><td colSpan={3} />
                      <td className="px-2 text-left font-mono">{n2(T.balance)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {tab === 'bridge' && <Grid tour="insurance-reports-bridge" rows={bridgeRows} initial="b_softech_edits_delta" cols={[
            ['claim_number', 'المطالبة', 'text'], ['client', 'الجهة', 'text'], ['b_import_net', 'قيمة الاستيراد', 'money'],
            ['b_softech_edits', 'إيصالات عُدّلت فى سوفتك', 'int'], ['b_softech_edits_delta', 'زيادة من تعديلات سوفتك', 'money'],
            ['b_catalog_delta', 'فرق تطبيق الكتالوج', 'money'], ['b_excluded_count', 'مستبعد', 'int'], ['b_excluded_net', 'قيمة المستبعد', 'money'],
            ['b_wrong_allocation', 'تخصيص خاطئ', 'int'], ['b_manual_count', 'إضافات يدوية', 'int'], ['b_manual_net', 'قيمة الإضافات', 'money'],
            ['b_from_other_count', 'من مطالبات أخرى', 'int'], ['b_from_other_net', 'قيمتها', 'money'],
            ['b_supplements_net', 'ملاحق', 'money'], ['b_other_adjustments', 'تعديلات أخرى', 'money'], ['b_final_net', 'القيمة النهائية', 'money']]} />}

          {tab === 'branches' && <Grid tour="insurance-reports-branches" rows={data.branches.map(b => ({ ...b, branch_label: bl(b.branch) }))} initial="net" cols={[
            ['branch_label', 'الفرع', 'text'], ['motalbas', 'مطالبات', 'int'], ['rx', 'روشتات', 'int'], ['net', 'الصافى', 'money'],
            ['patient_share', 'نصيب المريض', 'money'], ['revenue', 'الإيراد', 'money'], ['cost', 'التكلفة', 'money'], ['gp', 'مجمل الربح', 'money'], ['gp_pct', 'GP%', 'pct']]} />}

          {tab === 'claim_branch' && <Grid tour="insurance-reports-claim-branch" rows={data.by_branch_claim.map(b => ({ ...b, branch_label: bl(b.branch) }))} initial="net" cols={[
            ['claim_number', 'المطالبة', 'text'], ['branch_label', 'الفرع', 'text'], ['rx', 'روشتات', 'int'], ['net', 'الصافى', 'money'],
            ['revenue', 'الإيراد', 'money'], ['cost', 'التكلفة', 'money'], ['gp', 'مجمل الربح', 'money'], ['gp_pct', 'GP%', 'pct']]} />}

          {tab === 'sellers' && <Grid tour="insurance-reports-sellers" rows={data.sellers.map(b => ({ ...b, branch_label: bl(b.branch) }))} initial="net" cols={[
            ['seller', 'البائع', 'text'], ['branch_label', 'الفرع', 'text'], ['usercode', 'كود سوفتك', 'text'], ['rx', 'روشتات', 'int'],
            ['net', 'الصافى', 'money'], ['revenue', 'الإيراد', 'money'], ['cost', 'التكلفة', 'money'], ['gp', 'مجمل الربح', 'money'], ['gp_pct', 'GP%', 'pct']]} />}

          {tab === 'categories' && <Grid tour="insurance-reports-categories" rows={data.categories} initial="net" cols={[
            ['label', 'الفئة المالية', 'text'], ['gross', 'قبل الخصم', 'money'], ['net', 'الصافى', 'money'], ['cost', 'التكلفة', 'money'],
            ['gp', 'مجمل الربح', 'money'], ['gp_pct', 'GP%', 'pct']]} />}

          {tab === 'moves' && <Grid tour="insurance-reports-moves" rows={data.moves.map(m => ({ ...m, from_txt: m.from_claims.join('، ') || '—', branch_label: bl(m.branch) }))}
            initial="net" cols={[['to_claim', 'أُضيفت إلى', 'text'], ['from_txt', 'من المطالبة', 'text'], ['docnumber', 'الإيصال', 'text'],
              ['branch_label', 'الفرع', 'text'], ['patient', 'المريض', 'text'], ['net', 'الصافى', 'money'], ['note', 'ملاحظة', 'text']]} />}
        </>
      )}
    </div>
  )
}
