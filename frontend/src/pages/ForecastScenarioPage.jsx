/**
 * ForecastScenarioPage.jsx — /forecast-scenarios  (doc 16, Phase 3)
 * Factor-driven target generation: create a scenario, tune factors, generate
 * Model A / B / avg forecasts per branch, review, then commit to sales targets.
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { forecastApi } from '../api/client'
import useAuthStore from '../store/authStore'
import DataFreshnessBar from '../components/DataFreshnessBar'

const MONTHS = ['يناير','فبراير','مارس','أبريل','مايو','يونيو','يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر']
const MODELS = { a: 'Model A — نمو الهدف', b: 'Model B — مزيج مرجّح', avg: 'المتوسط (A+B)/2' }
const SCOPES = { branch: 'الفروع', salesperson: 'المندوبين', category: 'الفئات' }
const STATUS = {
  draft:     { label: 'مسودة',  cls: 'bg-gray-100 text-gray-600' },
  generated: { label: 'محسوب',  cls: 'bg-blue-100 text-blue-700' },
  committed: { label: 'معتمد',  cls: 'bg-emerald-100 text-emerald-700' },
}
const fmt = n => (Number(n) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })

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

      <DataFreshnessBar canEdit={canEdit} invalidateKeys={[['forecast-scenario'], ['forecast-results'], ['forecast-references']]} />
      <BacktestPanel canEdit={canEdit} />
      <ReferencesPanel canEdit={canEdit} />
      <ProfitExclusionPanel canEdit={canEdit} />

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

const REF_LABELS = { cash_delivery: 'نقدى+توصيل', credit: 'آجل', gross_profit: 'ربحية', customer_count: 'عملاء', beauty: 'تجميل', call_count: 'مكالمات' }

function ReferencesPanel({ canEdit }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [infl, setInfl] = useState('')
  const [rg, setRg] = useState('')
  const { data: refs = {} } = useQuery({
    queryKey: ['forecast-references'],
    queryFn: () => forecastApi.references().then(r => r.data),
  })
  const recompute = useMutation({
    mutationFn: () => forecastApi.computeReferences({
      inflation: infl !== '' ? Number(infl) : undefined,
      real_growth: rg !== '' ? Number(rg) : undefined,
    }),
    onSuccess: () => { setInfl(''); setRg(''); qc.invalidateQueries({ queryKey: ['forecast-references'] }) },
  })
  const metrics = Object.keys(refs.growth_goal || {})
  const pct = v => v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4 mb-4">
      <button onClick={() => setOpen(o => !o)} className="text-sm font-bold text-gray-800 flex items-center gap-2">
        <span>{open ? '▾' : '▸'}</span> 📐 القيم المرجعية (موسمية · نمو مرجعي · تضخم)
        {refs.as_of && <span className="text-[11px] text-gray-400 font-normal">— محدّثة {refs.as_of} · تضخم {pct(refs.inflation_annual)}/سنة</span>}
      </button>
      {open && (
        <div className="mt-3">
          {metrics.length === 0 ? (
            <p className="text-xs text-gray-400">لا توجد قيم محسوبة — اضغط «إعادة الحساب».</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 border-b border-gray-100">
                  <th className="text-right py-1">المؤشر</th>
                  <th className="text-center">النمو التاريخى YoY</th>
                  <th className="text-center">النمو المرجعى (B)</th>
                  <th className="text-center">هدف النمو (الخطة)</th>
                  <th className="text-center">موسمية أكتوبر</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map(m => (
                  <tr key={m} className="border-b border-gray-50">
                    <td className="py-1.5 font-medium text-gray-700">{REF_LABELS[m] || m}</td>
                    <td className="text-center tabular-nums text-gray-500">{pct(refs.historical_yoy?.[m])}</td>
                    <td className="text-center tabular-nums text-blue-700">{pct(refs.benchmark?.[m])}</td>
                    <td className="text-center tabular-nums font-semibold text-emerald-700">{pct(refs.growth_goal?.[m])}</td>
                    <td className="text-center tabular-nums text-gray-500">{refs.seasonality?.[m]?.['10'] ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-[10px] text-gray-400 mt-2">
            الموسمية والنمو التاريخى محسوبان من بيانات 24 شهراً. التضخم خارجى (CAPMAS) — حدّثه شهرياً.
            طبّق هذه القيم على سيناريو بزر «📐 تطبيق المرجعية».
          </p>
          {canEdit && (
            <div className="flex flex-wrap items-end gap-2 mt-2">
              <label className="text-[11px] text-gray-500">تضخم سنوى (مثال 0.145)
                <input className="input-field !w-28 mt-0.5" type="number" step="0.001" value={infl} onChange={e => setInfl(e.target.value)} placeholder={refs.inflation_annual ?? ''} />
              </label>
              <label className="text-[11px] text-gray-500">نمو حقيقى مستهدف (مثال 0.15)
                <input className="input-field !w-28 mt-0.5" type="number" step="0.01" value={rg} onChange={e => setRg(e.target.value)} placeholder={refs.real_growth ?? ''} />
              </label>
              <button onClick={() => recompute.mutate()} disabled={recompute.isPending}
                      className="btn-primary text-xs !py-2 disabled:opacity-40">
                {recompute.isPending ? '…' : 'إعادة الحساب / تحديث التضخم'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ProfitExclusionPanel({ canEdit }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const { data: rows = [] } = useQuery({
    queryKey: ['profit-exclusions'],
    queryFn: () => forecastApi.profitExclusions().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const inval = () => qc.invalidateQueries({ queryKey: ['profit-exclusions'] })
  const add = useMutation({
    mutationFn: () => forecastApi.profitExclusionAdd({ code: code.trim(), note: note.trim() }),
    onSuccess: () => { setCode(''); setNote(''); setErr(''); inval() },
    onError: (e) => setErr(e?.response?.data?.code || e?.response?.data?.detail || 'تعذّرت الإضافة'),
  })
  const toggle = useMutation({ mutationFn: ({ id, active }) => forecastApi.profitExclusionSet(id, { active }), onSuccess: inval })
  const del = useMutation({ mutationFn: (id) => forecastApi.profitExclusionDel(id), onSuccess: inval })

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4 mb-4">
      <button onClick={() => setOpen(o => !o)} className="text-sm font-bold text-gray-800 flex items-center gap-2">
        <span>{open ? '▾' : '▸'}</span> 🧮 استثناءات معامل الربحية
        <span className="text-[11px] text-gray-400 font-normal">— أصناف تُستبعد من حساب الربحية ({rows.length})</span>
      </button>
      {open && (
        <div className="mt-3">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-400 border-b border-gray-100">
                <th className="text-right py-1">الكود</th>
                <th className="text-right">الصنف</th>
                <th className="text-center">النوع</th>
                <th className="text-right">السبب</th>
                <th className="text-center">نشط</th>
                {canEdit && <th className="text-center">حذف</th>}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={6} className="text-center text-gray-400 py-3">لا توجد استثناءات</td></tr>}
              {rows.map(x => (
                <tr key={x.id} className="border-b border-gray-50">
                  <td className="py-1.5 font-mono text-gray-600">{x.item_code}</td>
                  <td className="font-medium text-gray-700">{x.item_name}</td>
                  <td className="text-center text-gray-400">{x.medicine_type}</td>
                  <td className="text-gray-500">{x.note}</td>
                  <td className="text-center">
                    <input type="checkbox" checked={x.active} disabled={!canEdit}
                      onChange={e => toggle.mutate({ id: x.id, active: e.target.checked })} />
                  </td>
                  {canEdit && (
                    <td className="text-center">
                      <button onClick={() => { if (confirm('حذف الاستثناء؟')) del.mutate(x.id) }}
                        className="text-gray-300 hover:text-red-500">✕</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {canEdit && (
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <input className="input-field !w-28" placeholder="كود الصنف" value={code} onChange={e => setCode(e.target.value)} />
              <input className="input-field !w-64" placeholder="السبب (اختياري)" value={note} onChange={e => setNote(e.target.value)} />
              <button onClick={() => add.mutate()} disabled={!code.trim() || add.isPending}
                className="btn-primary text-xs !py-2 disabled:opacity-40">{add.isPending ? '…' : '+ إضافة'}</button>
              {err && <span className="text-[11px] text-red-600">{err}</span>}
            </div>
          )}
          <p className="text-[10px] text-gray-400 mt-2">
            يُطبَّق فوراً على الحسابات الفورية؛ ويظهر في لوحة المؤشرات والتنبؤ بعد إعادة بناء المجاميع (build_kpi_rollups). لا يؤثر على المبيعات — الربحية فقط.
          </p>
        </div>
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
  const applyRefs = useMutation({ mutationFn: () => forecastApi.applyReferences(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['forecast-scenario', id] }) })
  const gen = useMutation({ mutationFn: () => forecastApi.generate(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ['forecast-scenario', id] }); refetchResults(); inval() } })
  const commit = useMutation({ mutationFn: () => forecastApi.commit(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ['forecast-scenario', id] }); inval() } })
  const del = useMutation({ mutationFn: () => forecastApi.remove(id), onSuccess: () => { onDeleted(); inval() } })
  const saveKnobs = useMutation({ mutationFn: (data) => forecastApi.update(id, data) })
  const saveFactors = useMutation({ mutationFn: (rows) => forecastApi.factors(id, rows) })

  // Lifted, editable form state — resynced whenever the scenario changes (after
  // apply-references / generate), so the UI always reflects the current factors.
  const [knobs, setKnobs] = useState(null)
  const [factorRows, setFactorRows] = useState([])
  const [recalcBusy, setRecalcBusy] = useState(false)
  useEffect(() => {
    if (!sc) return
    setKnobs({ model: sc.model, incentive_threshold: sc.incentive_threshold,
               benchmark_growth: sc.benchmark_growth, inflation: sc.inflation,
               promotion_lift: sc.promotion_lift })
    setFactorRows((sc.factors || []).map(f => ({ ...f })))
  }, [sc?.id, sc?.generated_at, sc?.model, sc?.inflation, JSON.stringify(sc?.factors)])

  // "احسب التنبؤ" — PERSIST the current edits (knobs + factors) then generate,
  // so changing a factor or the model is always reflected in the numbers.
  async function recalc() {
    setRecalcBusy(true)
    try {
      if (canEdit && knobs) await saveKnobs.mutateAsync(knobs)
      if (canEdit && factorRows.length) await saveFactors.mutateAsync(factorRows)
      await gen.mutateAsync()
    } finally { setRecalcBusy(false) }
  }

  if (!sc) return <div className="text-gray-400 text-sm py-8 text-center">جارٍ التحميل…</div>

  // group results per KPI → branch rows (sorted) + chain total row
  const metrics = [...new Set(results.map(r => r.metric))]
  const byMetric = metrics.map(m => ({
    metric: m,
    label: results.find(r => r.metric === m)?.metric_label || m,
    members: results.filter(r => r.metric === m && r.scope_key !== 'chain')
      .sort((a, b) => Number(b.target_value) - Number(a.target_value)),
    chain: results.find(r => r.metric === m && r.scope_key === 'chain'),
  }))

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl border border-gray-100 p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="font-bold text-gray-900">{sc.name}</div>
          {canEdit && <button onClick={() => { if (confirm('حذف السيناريو؟')) del.mutate() }} className="text-gray-300 hover:text-red-500 text-sm">حذف</button>}
        </div>

        {/* global knobs */}
        <GlobalKnobs value={knobs} onChange={setKnobs} canEdit={canEdit} />

        {/* per-metric factors */}
        <FactorTable rows={factorRows} onChange={setFactorRows} canEdit={canEdit} />

        {canEdit && (
          <div className="flex gap-2 mt-4 flex-wrap items-center">
            <button onClick={() => applyRefs.mutate()} disabled={applyRefs.isPending}
                    title="تطبيق القيم المرجعية (الموسمية + النمو المرجعي + التضخم) على عوامل هذا السيناريو"
                    className="text-sm px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40">
              {applyRefs.isPending ? '…' : '📐 تطبيق المرجعية'}
            </button>
            <button onClick={recalc} disabled={recalcBusy} className="btn-primary text-sm disabled:opacity-40">
              {recalcBusy ? 'جارٍ الحساب…' : '⚙️ حفظ واحسب التنبؤ'}
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

      {/* results — per KPI: branch rows then total */}
      {sc.status !== 'draft' && results.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-100 p-4">
          <div className="flex items-center justify-between mb-1">
            <div className="font-bold text-gray-800 text-sm">
              النتائج حسب {SCOPES[sc.scope_type] || 'الفروع'} ثم الإجمالى
            </div>
            <ExportScenarioButton id={id} year={sc.year} month={sc.month} />
          </div>
          <p className="text-[11px] text-gray-400 mb-3">الهدف = التنبؤ ÷ حد الحافز ({sc.incentive_threshold}) — لكل مؤشر: الفروع ثم الإجمالى.</p>
          <div className="space-y-5">
            {byMetric.map(({ metric, label, members, chain }) => (
              <div key={metric} className="overflow-x-auto">
                <div className="text-sm font-bold text-gray-800 bg-gray-50 rounded-t-lg px-3 py-1.5 border border-gray-100">{label}</div>
                <table className="w-full text-xs border-x border-b border-gray-100">
                  <thead>
                    <tr className="text-gray-400 bg-gray-50/50">
                      <th className="text-right py-1.5 px-3">{SCOPES[sc.scope_type] || 'الفرع'}</th>
                      <th className="text-center">الأساس (العام السابق)</th>
                      <th className="text-center">الشهر السابق</th>
                      <th className="text-center">قبل السابق</th>
                      <th className="text-center">Model A</th>
                      <th className="text-center">Model B</th>
                      <th className="text-center">التنبؤ</th>
                      <th className="text-center">الهدف</th>
                    </tr>
                  </thead>
                  <tbody>
                    {members.map(r => (
                      <tr key={r.id} className="border-t border-gray-50 hover:bg-gray-50/40">
                        <td className="py-1.5 px-3 font-medium text-gray-700">{r.scope_label}</td>
                        <td className="text-center tabular-nums text-gray-500">{fmt(r.base_value)}</td>
                        <td className="text-center tabular-nums text-gray-500">{fmt(r.lm_value)}</td>
                        <td className="text-center tabular-nums text-gray-500">{fmt(r.pm_value)}</td>
                        <td className="text-center tabular-nums">{fmt(r.model_a)}</td>
                        <td className="text-center tabular-nums">{fmt(r.model_b)}</td>
                        <td className="text-center tabular-nums font-semibold text-blue-700">{fmt(r.forecast_value)}</td>
                        <td className="text-center tabular-nums font-bold text-emerald-700">{fmt(r.target_value)}</td>
                      </tr>
                    ))}
                    {chain && (
                      <tr className="border-t-2 border-gray-200 bg-emerald-50/40 font-bold">
                        <td className="py-2 px-3 text-gray-900">الإجمالى</td>
                        <td className="text-center tabular-nums text-gray-600">{fmt(chain.base_value)}</td>
                        <td className="text-center tabular-nums text-gray-600">{fmt(chain.lm_value)}</td>
                        <td className="text-center tabular-nums text-gray-600">{fmt(chain.pm_value)}</td>
                        <td className="text-center tabular-nums">{fmt(chain.model_a)}</td>
                        <td className="text-center tabular-nums">{fmt(chain.model_b)}</td>
                        <td className="text-center tabular-nums text-blue-700">{fmt(chain.forecast_value)}</td>
                        <td className="text-center tabular-nums text-emerald-700">{fmt(chain.target_value)}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ExportScenarioButton({ id, year, month }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function run() {
    setBusy(true); setErr('')
    try {
      await downloadExport(() => forecastApi.exportScenario(id),
        `forecast_${year}_${String(month).padStart(2, '0')}.xlsx`)
    } catch (e) { setErr(e?.message || 'تعذّر التصدير') } finally { setBusy(false) }
  }
  return (
    <div className="flex items-center gap-2">
      {err && <span className="text-[11px] text-red-600">{err}</span>}
      <button onClick={run} disabled={busy}
        className="text-xs px-3 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40">
        {busy ? '… جارٍ' : '⬇️ تصدير إكسل'}
      </button>
    </div>
  )
}

function GlobalKnobs({ value, onChange, canEdit }) {
  if (!value) return null
  const set = (k, x) => onChange({ ...value, [k]: x })
  const Field = ({ k, label, step = '0.01' }) => (
    <label className="text-xs text-gray-500">{label}
      <input type="number" step={step} disabled={!canEdit} className="input-field mt-0.5"
        value={value[k] ?? ''} onChange={e => set(k, e.target.value)} />
    </label>
  )
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3 pb-3 border-b border-gray-50">
      <label className="text-xs text-gray-500">النموذج
        <select disabled={!canEdit} className="input-field mt-0.5" value={value.model} onChange={e => set('model', e.target.value)}>
          {Object.entries(MODELS).map(([k, x]) => <option key={k} value={k}>{x}</option>)}
        </select>
      </label>
      <Field k="incentive_threshold" label="حد الحافز (÷)" />
      <Field k="benchmark_growth" label="نمو مرجعي عام" />
      <Field k="inflation" label="التضخم (شهري)" />
      <Field k="promotion_lift" label="رفع العروض" />
    </div>
  )
}

const FACTOR_COLS = [
  ['growth_goal', 'هدف النمو (A)'], ['benchmark', 'نمو مرجعي (B)'],
  ['w_lm', 'وزن الشهر السابق'], ['w_pm', 'وزن قبل السابق'],
  ['w_yoy', 'وزن العام السابق'], ['seasonality_index', 'مؤشر موسمي'],
]

function FactorTable({ rows, onChange, canEdit }) {
  const upd = (i, k, val) => onChange(rows.map((r, j) => j === i ? { ...r, [k]: val } : r))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 border-b border-gray-100">
            <th className="text-right py-1">المؤشر</th>
            {FACTOR_COLS.map(([k, label]) => <th key={k} className="text-center px-1">{label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.metric} className="border-b border-gray-50">
              <td className="py-1 font-medium text-gray-700">{r.metric_label || REF_LABELS[r.metric] || r.metric}</td>
              {FACTOR_COLS.map(([k]) => (
                <td key={k} className="px-1">
                  <input type="number" step="0.01" disabled={!canEdit}
                    className="w-20 text-center border border-gray-200 rounded px-1 py-0.5"
                    value={r[k] ?? ''} onChange={e => upd(i, k, e.target.value === '' ? null : e.target.value)} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-gray-400 mt-1">
        A: هدف النمو · B: النمو المرجعي + أوزان الأشهر (يُفضّل مجموعها 1.0) + الموسمية. اضغط «حفظ واحسب التنبؤ» لتطبيق أى تعديل.
      </p>
    </div>
  )
}
