/**
 * ForecastScenarioPage.jsx — /forecast-scenarios  (doc 16, Phase 3)
 * Factor-driven target generation: create a scenario, tune factors, generate
 * Model A / B / avg forecasts per branch, review, then commit to sales targets.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { forecastApi } from '../api/client'
import useAuthStore from '../store/authStore'

const MONTHS = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
const MODELS = { a: 'Model A — نمو الهدف', b: 'Model B — مزيج مرجّح', avg: 'المتوسط (A+B)/2' }
const SCOPES = { branch: 'الفروع', salesperson: 'المندوبين', category: 'الفئات' }
const STATUS = {
  draft:     { label: 'مسودة',  cls: 'bg-gray-100 text-gray-600' },
  generated: { label: 'محسوب',  cls: 'bg-blue-100 text-blue-700' },
  committed: { label: 'معتمد',  cls: 'bg-emerald-100 text-emerald-700' },
}
const fmt = n => (Number(n) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })

export default function ForecastScenarioPage() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canEdit = ['admin', 'supervisor', 'purchasing'].includes(user?.role)
  const [selId, setSelId] = useState(null)
  const [showForm, setShowForm] = useState(false)

  const { data: scenarios = [], isLoading } = useQuery({
    queryKey: ['forecast-scenarios'],
    queryFn: () => forecastApi.list().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })

  return (
    <div className="p-6 max-w-[1400px] mx-auto" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🔮 سيناريوهات التنبؤ بالأهداف</h1>
          <p className="text-sm text-gray-500 mt-0.5">اضبط العوامل، احسب النموذج، ثم اعتمد الأهداف للفروع</p>
        </div>
        {canEdit && (
          <button onClick={() => setShowForm(s => !s)} className="btn-primary text-sm">
            {showForm ? 'إغلاق' : '+ سيناريو جديد'}
          </button>
        )}
      </div>

      <BacktestPanel canEdit={canEdit} />

      {showForm && canEdit && (
        <NewScenarioForm onDone={(id) => { setShowForm(false); setSelId(id); qc.invalidateQueries({ queryKey: ['forecast-scenarios'] }) }} />
      )}

      <div className="grid md:grid-cols-[280px_1fr] gap-4">
        {/* scenario list */}
        <div className="space-y-2">
          {isLoading ? <div className="text-gray-400 text-sm py-8 text-center">جارٍ التحميل…</div>
            : scenarios.length === 0 ? <div className="text-gray-400 text-sm py-8 text-center">لا توجد سيناريوهات</div>
            : scenarios.map(s => {
              const st = STATUS[s.status] || {}
              return (
                <button key={s.id} onClick={() => setSelId(s.id)}
                  className={`w-full text-right p-3 rounded-xl border transition ${selId === s.id ? 'border-blue-400 bg-blue-50/40' : 'border-gray-100 bg-white hover:border-gray-200'}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-gray-800 text-sm">{s.name}</span>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full ${st.cls}`}>{st.label}</span>
                  </div>
                  <div className="text-[11px] text-gray-400 mt-0.5">{MONTHS[s.month - 1]} {s.year} · {SCOPES[s.scope_type] || 'الفروع'} · {MODELS[s.model]}</div>
                </button>
              )
            })}
        </div>

        {/* detail */}
        <div>
          {selId ? <ScenarioDetail id={selId} canEdit={canEdit} onDeleted={() => setSelId(null)} />
            : <div className="text-gray-400 text-sm py-16 text-center border border-dashed border-gray-200 rounded-2xl">اختر سيناريو لعرض التفاصيل</div>}
        </div>
      </div>
    </div>
  )
}

function BacktestPanel({ canEdit }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const { data: runs = [] } = useQuery({
    queryKey: ['backtests'],
    queryFn: () => forecastApi.backtestList().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const latest = runs[0]
  const run = useMutation({
    mutationFn: () => forecastApi.backtestRun({ months_back: 12 }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['backtests'] }),
  })

  // group results by metric → {a, b}
  const byMetric = {}
  for (const r of (latest?.results || [])) {
    byMetric[r.metric] = byMetric[r.metric] || { label: r.metric_label }
    byMetric[r.metric][r.model] = r
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4 mb-4">
      <div className="flex items-center justify-between">
        <button onClick={() => setOpen(o => !o)} className="text-sm font-bold text-gray-800 flex items-center gap-2">
          <span>{open ? '▾' : '▸'}</span> 🏁 دقة النماذج (اختبار رجعي على التاريخ)
          {latest && <span className="text-[11px] text-gray-400 font-normal">— {latest.n_months} شهر</span>}
        </button>
        {canEdit && (
          <button onClick={() => run.mutate()} disabled={run.isPending}
            className="text-xs px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40">
            {run.isPending ? 'جارٍ الاختبار…' : 'تشغيل اختبار جديد'}
          </button>
        )}
      </div>

      {open && (
        latest ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 border-b border-gray-100">
                  <th className="text-right py-1">المؤشر</th>
                  <th className="text-center">A — WAPE%</th>
                  <th className="text-center">B — WAPE%</th>
                  <th className="text-center">الأفضل</th>
                  <th className="text-center">الانحياز (الفائز)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byMetric).map(([m, row]) => {
                  const win = row.a?.is_winner ? 'a' : (row.b?.is_winner ? 'b' : null)
                  const winner = win ? row[win] : null
                  return (
                    <tr key={m} className="border-b border-gray-50">
                      <td className="py-1.5 font-medium text-gray-700">{row.label}</td>
                      <td className={`text-center tabular-nums ${win === 'a' ? 'font-bold text-emerald-600' : 'text-gray-500'}`}>{row.a?.wape ?? '—'}</td>
                      <td className={`text-center tabular-nums ${win === 'b' ? 'font-bold text-emerald-600' : 'text-gray-500'}`}>{row.b?.wape ?? '—'}</td>
                      <td className="text-center font-bold text-emerald-700">{win ? `Model ${win.toUpperCase()}` : '—'}</td>
                      <td className="text-center tabular-nums text-gray-500">{winner ? `${winner.bias}%` : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="text-[11px] text-gray-400 mt-2">
              WAPE = متوسط الخطأ المطلق الموزون (أقل = أفضل). الفائز يعيد إنتاج التاريخ بأعلى دقة — استخدمه عند إنشاء السيناريو.
            </p>
          </div>
        ) : (
          <p className="text-xs text-gray-400 mt-2">لا يوجد اختبار بعد — شغّل اختباراً لمقارنة النموذجين على بيانات الأشهر السابقة.</p>
        )
      )}
    </div>
  )
}

function NewScenarioForm({ onDone }) {
  const now = new Date()
  const [f, setF] = useState({ name: '', year: now.getFullYear(), month: now.getMonth() + 1, scope_type: 'branch', model: 'a' })
  const create = useMutation({
    mutationFn: () => forecastApi.create(f),
    onSuccess: (r) => onDone(r.data.id),
  })
  const set = (k, v) => setF(s => ({ ...s, [k]: v }))
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4 mb-4 grid gap-2 md:grid-cols-5">
      <input className="input-field" placeholder="اسم السيناريو" value={f.name} onChange={e => set('name', e.target.value)} />
      <select className="input-field" value={f.scope_type} onChange={e => set('scope_type', e.target.value)}>
        {Object.entries(SCOPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <select className="input-field" value={f.month} onChange={e => set('month', +e.target.value)}>
        {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
      </select>
      <input className="input-field" type="number" value={f.year} onChange={e => set('year', +e.target.value)} />
      <select className="input-field" value={f.model} onChange={e => set('model', e.target.value)}>
        {Object.entries(MODELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <button onClick={() => create.mutate()} disabled={!f.name || create.isPending}
        className="btn-primary text-sm md:col-span-5 disabled:opacity-40">
        {create.isPending ? 'جارٍ الإنشاء…' : 'إنشاء'}
      </button>
    </div>
  )
}

function ScenarioDetail({ id, canEdit, onDeleted }) {
  const qc = useQueryClient()
  const inval = () => qc.invalidateQueries({ queryKey: ['forecast-scenarios'] })
  const { data: sc } = useQuery({ queryKey: ['forecast-scenario', id], queryFn: () => forecastApi.get(id).then(r => r.data) })
  const { data: results = [], refetch: refetchResults } = useQuery({
    queryKey: ['forecast-results', id],
    queryFn: () => forecastApi.results(id).then(r => r.data),
    enabled: !!sc && sc.status !== 'draft',
  })
  const gen = useMutation({ mutationFn: () => forecastApi.generate(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ['forecast-scenario', id] }); refetchResults(); inval() } })
  const commit = useMutation({ mutationFn: () => forecastApi.commit(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ['forecast-scenario', id] }); inval() } })
  const del = useMutation({ mutationFn: () => forecastApi.remove(id), onSuccess: () => { onDeleted(); inval() } })
  const saveKnobs = useMutation({ mutationFn: (data) => forecastApi.update(id, data), onSuccess: () => qc.invalidateQueries({ queryKey: ['forecast-scenario', id] }) })
  const saveFactors = useMutation({ mutationFn: (rows) => forecastApi.factors(id, rows), onSuccess: () => qc.invalidateQueries({ queryKey: ['forecast-scenario', id] }) })

  if (!sc) return <div className="text-gray-400 text-sm py-8 text-center">جارٍ التحميل…</div>

  // chain aggregate (scope_key='chain') + per-member rows per metric
  const metrics = [...new Set(results.map(r => r.metric))]
  const chainByMetric = Object.fromEntries(results.filter(r => r.scope_key === 'chain').map(r => [r.metric, r]))
  // top members by first metric's target (excludes the chain row)
  const primary = metrics[0]
  const members = results.filter(r => r.metric === primary && r.scope_key !== 'chain')
    .sort((a, b) => Number(b.target_value) - Number(a.target_value)).slice(0, 12)

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl border border-gray-100 p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="font-bold text-gray-900">{sc.name}</div>
          {canEdit && <button onClick={() => { if (confirm('حذف السيناريو؟')) del.mutate() }} className="text-gray-300 hover:text-red-500 text-sm">حذف</button>}
        </div>

        {/* global knobs */}
        <GlobalKnobs sc={sc} canEdit={canEdit} onSave={saveKnobs.mutate} />

        {/* per-metric factors */}
        <FactorTable sc={sc} canEdit={canEdit} onSave={saveFactors.mutate} />

        {canEdit && (
          <div className="flex gap-2 mt-4">
            <button onClick={() => gen.mutate()} disabled={gen.isPending} className="btn-primary text-sm disabled:opacity-40">
              {gen.isPending ? 'جارٍ الحساب…' : '⚙️ احسب التنبؤ'}
            </button>
            {sc.status !== 'draft' && (
              <button onClick={() => { if (confirm('اعتماد الأهداف للفروع؟')) commit.mutate() }} disabled={commit.isPending}
                className="text-sm px-4 py-2 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40">
                {commit.isPending ? 'جارٍ الاعتماد…' : '✅ اعتماد الأهداف'}
              </button>
            )}
            {sc.status === 'committed' && <span className="text-xs text-emerald-600 self-center">تم اعتماد الأهداف — تظهر في لوحة المؤشرات</span>}
          </div>
        )}
      </div>

      {/* results */}
      {sc.status !== 'draft' && results.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-100 p-4 overflow-x-auto">
          <div className="font-bold text-gray-800 mb-3 text-sm">النتائج (الإجمالى · {SCOPES[sc.scope_type] || 'الفروع'})</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs border-b border-gray-100">
                <th className="text-right py-2">المؤشر</th>
                <th className="text-center">الأساس (العام السابق)</th>
                <th className="text-center">Model A</th>
                <th className="text-center">Model B</th>
                <th className="text-center">التنبؤ</th>
                <th className="text-center">الهدف</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map(m => {
                const c = chainByMetric[m]
                if (!c) return null
                return (
                  <tr key={m} className="border-b border-gray-50">
                    <td className="py-2 font-medium text-gray-700">{c.metric_label}</td>
                    <td className="text-center tabular-nums text-gray-500">{fmt(c.base_value)}</td>
                    <td className="text-center tabular-nums">{fmt(c.model_a)}</td>
                    <td className="text-center tabular-nums">{fmt(c.model_b)}</td>
                    <td className="text-center tabular-nums font-semibold text-blue-700">{fmt(c.forecast_value)}</td>
                    <td className="text-center tabular-nums font-bold text-emerald-700">{fmt(c.target_value)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="text-[11px] text-gray-400 mt-2">الهدف = التنبؤ ÷ حد الحافز ({sc.incentive_threshold}). {primary && `التفصيل حسب ${SCOPES[sc.scope_type] || 'الفروع'} (${chainByMetric[primary]?.metric_label || ''}):`}</p>
          {members.length > 0 && (
            <table className="w-full text-xs mt-2">
              <thead>
                <tr className="text-gray-400 border-b border-gray-100">
                  <th className="text-right py-1">{SCOPES[sc.scope_type] || 'الفرع'}</th>
                  <th className="text-center">الأساس</th>
                  <th className="text-center">الشهر السابق</th>
                  <th className="text-center">التنبؤ</th>
                  <th className="text-center">الهدف</th>
                </tr>
              </thead>
              <tbody>
                {members.map(r => (
                  <tr key={r.id} className="border-b border-gray-50">
                    <td className="py-1 font-medium text-gray-700">{r.scope_label}</td>
                    <td className="text-center tabular-nums text-gray-500">{fmt(r.base_value)}</td>
                    <td className="text-center tabular-nums text-gray-500">{fmt(r.lm_value)}</td>
                    <td className="text-center tabular-nums font-semibold text-blue-700">{fmt(r.forecast_value)}</td>
                    <td className="text-center tabular-nums font-bold text-emerald-700">{fmt(r.target_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function GlobalKnobs({ sc, canEdit, onSave }) {
  const [v, setV] = useState({
    model: sc.model, incentive_threshold: sc.incentive_threshold,
    benchmark_growth: sc.benchmark_growth, inflation: sc.inflation, promotion_lift: sc.promotion_lift,
  })
  const set = (k, x) => setV(s => ({ ...s, [k]: x }))
  const Field = ({ k, label, step = '0.01' }) => (
    <label className="text-xs text-gray-500">{label}
      <input type="number" step={step} disabled={!canEdit} className="input-field mt-0.5" value={v[k]} onChange={e => set(k, e.target.value)} />
    </label>
  )
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3 pb-3 border-b border-gray-50">
      <label className="text-xs text-gray-500">النموذج
        <select disabled={!canEdit} className="input-field mt-0.5" value={v.model} onChange={e => set('model', e.target.value)}>
          {Object.entries(MODELS).map(([k, x]) => <option key={k} value={k}>{x}</option>)}
        </select>
      </label>
      <Field k="incentive_threshold" label="حد الحافز (÷)" />
      <Field k="benchmark_growth" label="نمو مرجعي" />
      <Field k="inflation" label="التضخم" />
      <Field k="promotion_lift" label="رفع العروض" />
      {canEdit && (
        <button onClick={() => onSave(v)} className="text-xs px-3 py-2 rounded-lg bg-gray-100 hover:bg-gray-200 md:col-span-5 justify-self-start">
          حفظ العوامل العامة
        </button>
      )}
    </div>
  )
}

function FactorTable({ sc, canEdit, onSave }) {
  const [rows, setRows] = useState(() => (sc.factors || []).map(f => ({ ...f })))
  const upd = (i, k, val) => setRows(rs => rs.map((r, j) => j === i ? { ...r, [k]: val } : r))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-gray-100">
            <th className="text-right py-1">المؤشر</th>
            <th className="text-center">هدف النمو (A)</th>
            <th className="text-center">وزن الشهر السابق</th>
            <th className="text-center">وزن قبل السابق</th>
            <th className="text-center">وزن العام السابق</th>
            <th className="text-center">مؤشر موسمي</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.metric} className="border-b border-gray-50">
              <td className="py-1 font-medium text-gray-700">{r.metric_label}</td>
              {['growth_goal', 'w_lm', 'w_pm', 'w_yoy', 'seasonality_index'].map(k => (
                <td key={k} className="px-1">
                  <input type="number" step="0.01" disabled={!canEdit} className="w-20 text-center border border-gray-200 rounded px-1 py-0.5"
                    value={r[k]} onChange={e => upd(i, k, e.target.value)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {canEdit && (
        <button onClick={() => onSave(rows)} className="text-xs px-3 py-1.5 mt-2 rounded-lg bg-gray-100 hover:bg-gray-200">
          حفظ عوامل المؤشرات
        </button>
      )}
      <p className="text-[10px] text-gray-400 mt-1">أوزان Model B يُفضّل أن يكون مجموعها 1.0 لكل مؤشر.</p>
    </div>
  )
}
