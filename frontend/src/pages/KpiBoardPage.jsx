/**
 * KpiBoardPage.jsx — /kpi-board  (doc 16)
 * Daily follow-up: branch × KPI matrix (تارجت/تحقيق). Achieved from KpiActualRollup;
 * targets are the EDITABLE SalesTargets (inline edit, or bulk «اعتمد من سيناريو»).
 * % is achievement vs the target pro-rated to the latest COMPLETE data day.
 */
import { Fragment, useState } from 'react'
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
const fmt = (n, count) => n == null ? '—'
  : Number(n).toLocaleString('en-US', { maximumFractionDigits: count ? 0 : 0 })
const pad = n => String(n).padStart(2, '0')

async function downloadExport(fetcher, filename) {
  const r = await fetcher()
  const data = r.data
  if (data instanceof Blob && data.type.includes('json')) {
    throw new Error(JSON.parse(await data.text()).detail || 'تعذّر التصدير')
  }
  const blob = data instanceof Blob ? data
    : new Blob([data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}

function pctColor(pct) {
  if (pct == null) return 'text-gray-400'
  if (pct >= 100) return 'text-emerald-600 font-bold'
  if (pct >= 90)  return 'text-emerald-600'
  if (pct >= 75)  return 'text-amber-600'
  return 'text-red-600'
}

// Editable target <td>. Click (admin) → number input → save via onSave.
function TargetCell({ c, branchId, metric, isCount, canEdit, onSave, strong }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState('')
  const start = () => { setVal(c.target != null ? String(c.target) : ''); setEditing(true) }
  const commit = () => {
    setEditing(false)
    const v = val.trim()
    if (v !== '' && Number(v) !== Number(c.target || 0)) {
      onSave({ target_id: c.target_id, branch_id: branchId, metric, value: Number(v) })
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
    <td onClick={canEdit ? start : undefined}
        title={canEdit ? 'اضغط لتعديل الهدف' : undefined}
        className={`px-2 py-2.5 text-center tabular-nums ${strong ? 'text-gray-500' : 'text-gray-400'} ${canEdit ? 'cursor-pointer hover:bg-blue-50/60' : ''}`}>
      {fmt(c.target, isCount)}
      {canEdit && <span className="text-[8px] text-blue-300 align-top"> ✎</span>}
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

// MTD (pro-rated to the data-through date) target — read-only.
function MtdTarget({ c, isCount }) {
  return <td className="px-2 py-2.5 text-center tabular-nums text-indigo-600">{fmt(c.target_todate, isCount)}</td>
}

// The 3 sub-headers repeated per metric: full-month target · MTD target · % .
function SubHeaders({ metrics }) {
  return (
    <tr className="bg-gray-50/60 text-[11px] text-gray-400">
      <th className="sticky right-0 bg-gray-50/60"></th>
      {metrics.map(m => (
        <Fragment key={m.key}>
          <th className="px-2 py-1 font-medium border-r border-gray-100">محقق</th>
          <th className="px-2 py-1 font-medium text-indigo-500">حتى تاريخه</th>
          <th className="px-2 py-1 font-medium">تارجت الشهر</th>
          <th className="px-2 py-1 font-medium">% التحقيق</th>
        </Fragment>
      ))}
    </tr>
  )
}

function CallCenterBlock({ cc, canEdit, onSave }) {
  const metrics = cc.metrics || []
  return (
    <div className="bg-white rounded-2xl border border-gray-100 overflow-x-auto mt-4">
      <div className="px-4 pt-3 pb-1 font-bold text-gray-800 text-sm">📞 الكول سنتر</div>
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 text-gray-600">
            <th></th>
            {metrics.map(m => (
              <th key={m.key} className="px-3 py-2 text-center font-bold border-r border-gray-100" colSpan={4}>{m.label}</th>
            ))}
          </tr>
          <SubHeaders metrics={metrics} />
        </thead>
        <tbody>
          <tr>
            <td className="sticky right-0 bg-white px-2 text-[11px] text-gray-400">الكول سنتر</td>
            {metrics.map(m => {
              const c = cc.cells[m.key] || {}
              return (
                <Fragment key={m.key}>
                  <td className="px-2 py-2.5 text-center tabular-nums text-gray-800 border-r border-gray-50">{fmt(c.actual, m.is_count)}</td>
                  <MtdTarget c={c} isCount={m.is_count} />
                  <TargetCell c={c} branchId={cc.branch_id} metric={m.key} isCount={m.is_count} canEdit={canEdit} onSave={onSave} />
                  <MetricPct c={c} />
                </Fragment>
              )
            })}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

const EXPORT_MODELS = [
  { value: 'a,b,avg', label: 'كل النماذج (A · B · المتوسط)' },
  { value: 'avg',     label: 'المتوسط (A+B)' },
  { value: 'a',       label: 'Model A — نمو الهدف' },
  { value: 'b',       label: 'Model B — مزيج مرجّح' },
]

export default function KpiBoardPage() {
  const now = new Date()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canEdit = ['admin', 'supervisor', 'purchasing'].includes(user?.role)
  const [year, setYear]   = useState(now.getFullYear())
  const [month, setMonth] = useState(now.getMonth() + 1)
  const [exportModel, setExportModel] = useState('a,b,avg')
  const [exporting, setExporting]     = useState(false)
  const [exportErr, setExportErr]     = useState('')
  const [pullSid, setPullSid]         = useState('')
  const [msg, setMsg]                 = useState('')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['kpi-board', year, month],
    queryFn: () => kpiApi.board({ year, month }).then(r => r.data),
  })

  const { data: scenarios = [] } = useQuery({
    queryKey: ['scenarios-for-board'],
    enabled: canEdit,
    queryFn: () => forecastApi.list().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const branchScenarios = scenarios.filter(s => s.scope_type === 'branch' && s.year === year && s.month === month)

  const monthStart = `${year}-${pad(month)}-01`
  const monthEnd   = `${year}-${pad(month)}-${pad(new Date(year, month, 0).getDate())}`

  const saveTarget = useMutation({
    mutationFn: ({ target_id, branch_id, metric, value }) => target_id
      ? targetsApi.update(target_id, { target_value: value })
      : targetsApi.create({ scope_type: 'branch', branch: branch_id, metric,
          period_start: monthStart, period_end: monthEnd, target_value: value,
          label: `${MONTHS[month - 1]} ${year}` }),
    onSuccess: () => { setMsg('تم حفظ الهدف'); qc.invalidateQueries({ queryKey: ['kpi-board', year, month] }) },
    onError: () => setMsg('تعذّر حفظ الهدف'),
  })
  const pull = useMutation({
    mutationFn: (sid) => forecastApi.commit(sid),
    onSuccess: (r) => { setMsg(`تم اعتماد الأهداف من السيناريو (${r?.data?.targets_committed ?? ''})`); qc.invalidateQueries({ queryKey: ['kpi-board', year, month] }) },
    onError: () => setMsg('تعذّر الاعتماد من السيناريو'),
  })

  async function handleExport() {
    setExporting(true); setExportErr('')
    try {
      await downloadExport(() => kpiApi.exportSheet({ year, month, models: exportModel }),
        `kpi_target_${year}_${pad(month)}.xlsx`)
    } catch (e) { setExportErr(e?.message || 'تعذّر إنشاء ملف الإكسل') } finally { setExporting(false) }
  }

  const metrics = data?.metrics || []
  const onSave = (p) => saveTarget.mutate(p)

  return (
    <div className="p-6 max-w-[1400px] mx-auto" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">📊 لوحة مؤشرات الفروع</h1>
          <p className="text-sm text-gray-500 mt-0.5">المتابعة اليومية — {MONTHS[month - 1]} {year}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select className="input-field !w-auto" value={month} onChange={e => setMonth(+e.target.value)}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select className="input-field !w-auto" value={year} onChange={e => setYear(+e.target.value)}>
            {[year + 1, year, year - 1, year - 2].map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          {canEdit && (
            <>
              <span className="w-px h-6 bg-gray-200 mx-1" />
              <select className="input-field !w-auto" value={pullSid} onChange={e => setPullSid(e.target.value)}
                      title="اعتمد الأهداف من سيناريو تنبؤ">
                <option value="">اعتمد من سيناريو…</option>
                {branchScenarios.map(s => <option key={s.id} value={s.id}>{s.name} ({s.model_label || s.model})</option>)}
              </select>
              <button onClick={() => pullSid && pull.mutate(pullSid)} disabled={!pullSid || pull.isPending}
                      className="text-sm px-3 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40">
                {pull.isPending ? '…' : 'اعتماد'}
              </button>
            </>
          )}
          <span className="w-px h-6 bg-gray-200 mx-1" />
          <select className="input-field !w-auto" value={exportModel} onChange={e => setExportModel(e.target.value)}
                  title="نموذج التنبؤ للتارجت في ملف الإكسل">
            {EXPORT_MODELS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <button onClick={handleExport} disabled={exporting}
                  className="btn-primary !py-2 whitespace-nowrap disabled:opacity-60">
            {exporting ? '… جارٍ' : '⬇️ تصدير إكسل'}
          </button>
        </div>
      </div>

      {/* data freshness + sync (like التقارير السردية) */}
      {data && (
        <DataFreshnessBar dataThrough={data.data_through} daysElapsed={data.days_elapsed}
          daysTotal={data.days_total} canEdit={canEdit} invalidateKeys={[['kpi-board', year, month]]} />
      )}
      <p className="text-[11px] text-gray-400 mb-2">
        الترتيب: محقق · حتى تاريخه (الهدف المحسوب حتى اليوم) · تارجت الشهر (الهدف الكامل) · % التحقيق (= المحقق ÷ حتى تاريخه). كل الأرقام بنظام الشهر حتى تاريخه (MTD).
      </p>
      {msg && <div className="mb-2 text-sm text-emerald-700 bg-emerald-50 rounded-lg px-3 py-1.5">{msg}</div>}
      {exportErr && <div className="mb-3 text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{exportErr}</div>}

      {isLoading ? (
        <div className="text-center py-16 text-gray-400">جارٍ التحميل…</div>
      ) : isError ? (
        <div className="text-center py-16 text-red-400">تعذّر تحميل اللوحة</div>
      ) : !data?.has_data ? (
        <div className="text-center py-16 text-gray-400">
          لا توجد بيانات محسوبة لهذا الشهر.
          <div className="text-xs mt-2 text-gray-400">شغّل <code>build_kpi_rollups --year {year} --month {month}</code></div>
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-100 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 text-gray-600">
                <th className="text-right font-bold px-4 py-3 sticky right-0 bg-gray-50">الفرع</th>
                {metrics.map(m => (
                  <th key={m.key} className="px-3 py-3 text-center font-bold border-r border-gray-100" colSpan={4}>{m.label}</th>
                ))}
              </tr>
              <SubHeaders metrics={metrics} />
            </thead>
            <tbody>
              {data.branches.map(b => (
                <tr key={b.branch_id} className="border-t border-gray-50 hover:bg-gray-50/40">
                  <td className="px-4 py-2.5 sticky right-0 bg-white">
                    <div className="font-bold text-gray-800">{b.name}</div>
                    <div className="text-[11px] text-gray-400">{b.code}</div>
                  </td>
                  {metrics.map(m => {
                    const c = b.cells[m.key] || {}
                    return (
                      <Fragment key={m.key}>
                        <td className="px-2 py-2.5 text-center tabular-nums text-gray-800 border-r border-gray-50">{fmt(c.actual, m.is_count)}</td>
                        <MtdTarget c={c} isCount={m.is_count} />
                        <TargetCell c={c} branchId={b.branch_id} metric={m.key} isCount={m.is_count} canEdit={canEdit} onSave={onSave} />
                        <MetricPct c={c} />
                      </Fragment>
                    )
                  })}
                </tr>
              ))}
              {/* Chain totals (read-only sum) */}
              <tr className="border-t-2 border-gray-200 bg-gray-50 font-bold">
                <td className="px-4 py-3 sticky right-0 bg-gray-50 text-gray-900">إجمالى الفروع</td>
                {metrics.map(m => {
                  const c = data.totals[m.key] || {}
                  return (
                    <Fragment key={m.key}>
                      <td className="px-2 py-3 text-center tabular-nums text-gray-900 border-r border-gray-100">{fmt(c.actual, m.is_count)}</td>
                      <td className="px-2 py-3 text-center tabular-nums text-indigo-600">{fmt(c.target_todate, m.is_count)}</td>
                      <td className="px-2 py-3 text-center tabular-nums text-gray-500 border-r border-gray-50">{fmt(c.target, m.is_count)}</td>
                      <MetricPct c={c} />
                    </Fragment>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {data?.call_center && <CallCenterBlock cc={data.call_center} canEdit={canEdit} onSave={onSave} />}

      <p className="text-[11px] text-gray-400 mt-3">
        القيم المالية بالجنيه · «محقق» من فواتير SOFTECH (صافى بعد المرتجعات) · «تارجت» قابل للتعديل (اضغط على الخلية){canEdit ? '' : ' — للمصرّح لهم'} أو «اعتمد من سيناريو».
        تُدار الأهداف أيضاً من <a href="/targets" className="text-blue-500 hover:underline">الأهداف البيعية</a>.
      </p>
    </div>
  )
}
