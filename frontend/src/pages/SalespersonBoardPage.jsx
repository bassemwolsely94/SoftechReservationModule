/**
 * SalespersonBoardPage.jsx — /salesperson-board  (doc 16)
 * Daily follow-up for SALESPEOPLE with an assigned target this month: مندوب × KPI matrix
 * (تارجت/تحقيق). There is no salesperson rollup, so «محقق» is resolved LIVE on the server
 * per rep; targets are the EDITABLE SalesTargets (inline edit, bulk «اعتمد من سيناريو», or
 * per-cell «⤓»). % is achievement vs the target pro-rated to the latest COMPLETE data day.
 */
import { Fragment, useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { kpiApi, targetsApi, forecastApi } from '../api/client'
import useAuthStore from '../store/authStore'
import DataFreshnessBar from '../components/DataFreshnessBar'

const MONTHS = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
const PACE = {
  ahead:   { label: 'متقدّم',  cls: 'text-emerald-700 bg-emerald-50' },
  behind:  { label: 'متأخّر',  cls: 'text-amber-700 bg-amber-50' },
  met:     { label: 'تحقّق',   cls: 'text-emerald-700 bg-emerald-50' },
  missed:  { label: 'لم يتحقق', cls: 'text-red-700 bg-red-50' },
  pending: { label: '—',       cls: 'text-gray-400 bg-gray-50' },
}
const fmt = (n) => n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })
const pad = n => String(n).padStart(2, '0')

function pctColor(pct) {
  if (pct == null) return 'text-gray-400'
  if (pct >= 100) return 'text-emerald-600 font-bold'
  if (pct >= 90)  return 'text-emerald-600'
  if (pct >= 75)  return 'text-amber-600'
  return 'text-red-600'
}

// Editable target <td>. Click (admin) → number input → save. «⤓» pulls just this cell from
// the selected scenario's forecast (onPull), without committing the whole scenario.
function TargetCell({ c, user, metric, canEdit, onSave, onPull, pulling }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState('')
  const start = () => { setVal(c.target != null ? String(c.target) : ''); setEditing(true) }
  const commit = () => {
    setEditing(false)
    const v = val.trim()
    if (v !== '' && Number(v) !== Number(c.target || 0)) {
      onSave({ target_id: c.target_id, softech_user: user, metric, value: Number(v) })
    }
  }
  if (editing) {
    return (
      <td className="px-1 py-2 text-center border-r border-gray-50">
        <input autoFocus type="number" value={val} onChange={e => setVal(e.target.value)}
          onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(false) }}
          className="w-24 text-center border border-blue-300 rounded px-1 py-0.5 tabular-nums" />
      </td>
    )
  }
  return (
    <td data-tour="salesperson-board-target" onClick={canEdit ? start : undefined}
        title={canEdit ? 'اضغط لتعديل الهدف' : undefined}
        className={`px-2 py-2.5 text-center tabular-nums text-gray-400 ${canEdit ? 'cursor-pointer hover:bg-blue-50/60' : ''}`}>
      {fmt(c.target)}
      {canEdit && <span className="text-[8px] text-blue-300 align-top"> ✎</span>}
      {canEdit && onPull && (
        <button type="button" disabled={pulling}
          onClick={e => { e.stopPropagation(); onPull({ scope_key: user, metric }) }}
          title="اعتمد هذا الهدف من السيناريو المختار"
          className="align-top text-[8px] text-emerald-500 hover:text-emerald-700 disabled:opacity-40">
          {pulling ? '…' : ' ⤓'}
        </button>
      )}
    </td>
  )
}

function MetricPct({ c }) {
  const pace = PACE[c.pace] || {}
  return (
    <td className={`px-2 py-2.5 text-center tabular-nums ${pctColor(c.pct)}`}>
      {c.pct == null ? '—' : `${c.pct}%`}
      {c.pace && c.pace !== 'pending' && (
        <span className={`block text-[9px] rounded px-1 mt-0.5 ${pace.cls}`}>{pace.label}</span>
      )}
    </td>
  )
}

const SUB_COLS = [['actual', 'محقق'], ['target_todate', 'حتى تاريخه'], ['target', 'تارجت الشهر'], ['pct', '% التحقيق']]
function SubHeaders({ metrics, sort, onSort }) {
  const arrow = (m, f) => (sort && sort.metric === m && sort.field === f) ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''
  return (
    <tr className="bg-gray-50/60 text-[11px] text-gray-400">
      <th className="sticky right-0 bg-gray-50/60"></th>
      {metrics.map(m => (
        <Fragment key={m.key}>
          {SUB_COLS.map(([f, label], i) => (
            <th key={f} onClick={onSort ? () => onSort(m.key, f) : undefined}
              className={`px-2 py-1 font-medium ${i === 0 ? 'border-r border-gray-100' : ''} ${f === 'target_todate' ? 'text-indigo-500' : ''} ${onSort ? 'cursor-pointer hover:text-gray-700 select-none' : ''}`}>
              {label}{arrow(m.key, f)}
            </th>
          ))}
        </Fragment>
      ))}
    </tr>
  )
}

export default function SalespersonBoardPage() {
  const now = new Date()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canEdit = ['admin', 'supervisor', 'purchasing'].includes(user?.role)
  const [year, setYear]   = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [pullSid, setPullSid] = useState('')
  const [msg, setMsg]         = useState('')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['salesperson-board', year, month],
    queryFn: () => kpiApi.salespersonBoard({ year, month }).then(r => r.data),
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios-for-sp-board'],
    enabled: canEdit,
    queryFn: () => forecastApi.list().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const spScenarios = scenarios.filter(s => s.scope_type === 'salesperson' && s.year === year && s.month === month)

  const monthStart = `${year}-${pad(month)}-01`
  const monthEnd   = `${year}-${pad(month)}-${pad(new Date(year, month, 0).getDate())}`

  const saveTarget = useMutation({
    mutationFn: ({ target_id, softech_user, metric, value }) => target_id
      ? targetsApi.update(target_id, { target_value: value })
      : targetsApi.create({ scope_type: 'salesperson', softech_user, metric,
          period_start: monthStart, period_end: monthEnd, target_value: value,
          label: `${MONTHS[month - 1]} ${year}` }),
    onSuccess: () => { setMsg('تم حفظ الهدف'); qc.invalidateQueries({ queryKey: ['salesperson-board', year, month] }) },
    onError: () => setMsg('تعذّر حفظ الهدف'),
  })
  const onSave = (p) => saveTarget.mutate(p)

  const pull = useMutation({
    mutationFn: (sid) => forecastApi.commit(sid),
    onSuccess: (r) => { setMsg(`تم اعتماد الأهداف من السيناريو (${r?.data?.targets_committed ?? ''})`); qc.invalidateQueries({ queryKey: ['salesperson-board', year, month] }) },
    onError: () => setMsg('تعذّر الاعتماد من السيناريو'),
  })
  const [pullingKey, setPullingKey] = useState('')
  const pullCell = useMutation({
    mutationFn: ({ scope_key, metric }) => forecastApi.commitCell(pullSid, { scope_key, metric }),
    onMutate: ({ scope_key, metric }) => setPullingKey(`${scope_key}:${metric}`),
    onSuccess: () => { setMsg('تم اعتماد هذا الهدف من النموذج'); qc.invalidateQueries({ queryKey: ['salesperson-board', year, month] }) },
    onError: (e) => setMsg(e?.response?.data?.detail || 'تعذّر اعتماد الهدف من النموذج'),
    onSettled: () => setPullingKey(''),
  })
  const onPull = pullSid ? (p) => pullCell.mutate(p) : null

  const metrics = data?.metrics || []

  const [sort, setSort] = useState(null)
  const onSort = (metric, field) => setSort(s =>
    (s && s.metric === metric && s.field === field)
      ? (s.dir === 'desc' ? { metric, field, dir: 'asc' } : null)
      : { metric, field, dir: 'desc' })
  const sortedReps = useMemo(() => {
    const arr = [...(data?.salespeople || [])]
    if (sort) arr.sort((a, b) => {
      const av = Number(a.cells[sort.metric]?.[sort.field] ?? 0)
      const bv = Number(b.cells[sort.metric]?.[sort.field] ?? 0)
      return sort.dir === 'asc' ? av - bv : bv - av
    })
    return arr
  }, [data, sort])

  return (
    <div className="p-6 max-w-[1400px] mx-auto" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🧑‍💼 متابعة المندوبين</h1>
          <p className="text-sm text-gray-500 mt-0.5">المتابعة اليومية للمندوبين المخصّص لهم تارجت — {MONTHS[month - 1]} {year}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap" data-tour="salesperson-board-period">
          <select className="input-field !w-auto" value={month} onChange={e => setMonth(+e.target.value)}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select className="input-field !w-auto" value={year} onChange={e => setYear(+e.target.value)}>
            {[year + 1, year, year - 1, year - 2].map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          {canEdit && (
            <>
              <span className="w-px h-6 bg-gray-200 mx-1" />
              <select data-tour="salesperson-board-scenario" className="input-field !w-auto" value={pullSid} onChange={e => setPullSid(e.target.value)}
                      title="اعتمد الأهداف من سيناريو تنبؤ للمندوبين">
                <option value="">اعتمد من سيناريو…</option>
                {spScenarios.map(s => <option key={s.id} value={s.id}>{s.name} ({s.model_label || s.model})</option>)}
              </select>
              <button data-tour="salesperson-board-approve" onClick={() => pullSid && pull.mutate(pullSid)} disabled={!pullSid || pull.isPending}
                      className="text-sm px-3 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40">
                {pull.isPending ? '…' : 'اعتماد'}
              </button>
            </>
          )}
        </div>
      </div>

      {data && (
        <DataFreshnessBar dataThrough={data.data_through} daysElapsed={data.days_elapsed}
          daysTotal={data.days_total} canEdit={canEdit} invalidateKeys={[['salesperson-board', year, month]]} />
      )}
      <p className="text-[11px] text-gray-400 mb-2">
        الترتيب: محقق · حتى تاريخه (الهدف المحسوب حتى اليوم) · تارجت الشهر (الهدف الكامل) · % التحقيق (= المحقق ÷ حتى تاريخه). «محقق» محسوب لحظياً من فواتير المندوب (مفيش مجاميع مخزّنة للمندوبين) فقد يأخذ ثوانٍ.
      </p>
      {msg && <div className="mb-2 text-sm text-emerald-700 bg-emerald-50 rounded-lg px-3 py-1.5">{msg}</div>}

      {isLoading ? (
        <div className="text-center py-16 text-gray-400">جارٍ التحميل…</div>
      ) : isError ? (
        <div className="text-center py-16 text-red-400">تعذّر تحميل اللوحة</div>
      ) : !data?.has_data ? (
        <div className="text-center py-16 text-gray-400">
          لا يوجد مندوبون لهم تارجت هذا الشهر.
          <div className="text-xs mt-2 text-gray-400">اعتمد سيناريو مندوبين من شاشة السيناريوهات، أو أضف أهدافاً من «الأهداف البيعية».</div>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-x-auto" data-tour="salesperson-board-table">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-gray-600">
                <th className="text-right font-bold px-4 py-3 sticky right-0 bg-gray-50">المندوب</th>
                {metrics.map(m => (
                  <th key={m.key} className="px-3 py-3 text-center font-bold border-r border-gray-100" colSpan={4}>{m.label}</th>
                ))}
              </tr>
              <SubHeaders metrics={metrics} sort={sort} onSort={onSort} />
            </thead>
            <tbody>
              {sortedReps.map(rep => (
                <tr key={rep.softech_user} className="border-t border-gray-50 hover:bg-gray-50/40">
                  <td className="px-4 py-2.5 sticky right-0 bg-white">
                    <div className="font-bold text-gray-800">{rep.label}</div>
                    <div className="text-[11px] text-gray-400">#{rep.softech_user}</div>
                  </td>
                  {metrics.map(m => {
                    const c = rep.cells[m.key] || {}
                    return (
                      <Fragment key={m.key}>
                        <td className="px-2 py-2.5 text-center tabular-nums text-gray-800 border-r border-gray-50">{fmt(c.actual)}</td>
                        <td className="px-2 py-2.5 text-center tabular-nums text-indigo-600">{fmt(c.target_todate)}</td>
                        <TargetCell c={c} user={rep.softech_user} metric={m.key}
                          canEdit={canEdit} onSave={onSave} onPull={onPull}
                          pulling={pullingKey === `${rep.softech_user}:${m.key}`} />
                        <MetricPct c={c} />
                      </Fragment>
                    )
                  })}
                </tr>
              ))}
              <tr className="border-t-2 border-gray-200 bg-gray-50 font-bold">
                <td className="px-4 py-3 sticky right-0 bg-gray-50 text-gray-900">الإجمالى</td>
                {metrics.map(m => {
                  const c = data.totals[m.key] || {}
                  return (
                    <Fragment key={m.key}>
                      <td className="px-2 py-3 text-center tabular-nums text-gray-900 border-r border-gray-100">{fmt(c.actual)}</td>
                      <td className="px-2 py-3 text-center tabular-nums text-indigo-600">{fmt(c.target_todate)}</td>
                      <td className="px-2 py-3 text-center tabular-nums text-gray-500 border-r border-gray-50">{fmt(c.target)}</td>
                      <MetricPct c={c} />
                    </Fragment>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-gray-400 mt-3">
        القيم المالية بالجنيه · «محقق» من فواتير SOFTECH (صافى بعد المرتجعات) · «تارجت» قابل للتعديل (اضغط على الخلية){canEdit ? '' : ' — للمصرّح لهم'} أو «اعتمد من سيناريو» (كامل)، أو «⤓» لاعتماد خلية واحدة من النموذج المختار.
        تُدار الأهداف أيضاً من <a href="/targets" className="text-blue-500 hover:underline">الأهداف البيعية</a>.
      </p>
    </div>
  )
}
