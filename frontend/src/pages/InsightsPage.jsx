/**
 * InsightsPage.jsx — /insights  (doc 18)
 * Bilingual narrative audit reports (day/week/month): generate, read AR/EN,
 * copy for WhatsApp. Large, clean layout for non-technical directors.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { insightsApi } from '../api/client'
import useAuthStore from '../store/authStore'

const PERIODS = { day: 'يومي', week: 'أسبوعي', mtd: 'حتى تاريخه', month: 'شهري' }

// ── date helpers (ISO yyyy-mm-dd) — all UTC math so there's no timezone drift ──
// (mixing `new Date(iso+'T00:00')` [local] with `.toISOString()` [UTC] shifts the
//  day by ±1 in non-UTC zones, which broke the exact 7-day week selection.)
const pad2 = (n) => String(n).padStart(2, '0')
const isoToday = () => { const d = new Date(); return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}` }
const addDays = (iso, n) => { const [y, m, d] = iso.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10) }
const daysBetween = (a, b) => { const [ay, am, ad] = a.split('-').map(Number), [by, bm, bd] = b.split('-').map(Number); return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86400000) + 1 }
const dow = (iso) => { const [y, m, d] = iso.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)).getUTCDay() }  // 0=Sun … 5=Fri … 6=Sat
const monthBounds = (ym) => {   // ym = 'yyyy-mm' → {start: 1st, end: last day}
  const [y, m] = ym.split('-').map(Number)
  const start = `${ym}-01`
  const last = new Date(y, m, 0).getDate()
  return { start, end: `${ym}-${String(last).padStart(2, '0')}` }
}
function defaultRange(p) {
  const y = addDays(isoToday(), -1)   // yesterday (last complete day)
  if (p === 'day') return { start: y, end: y }
  if (p === 'week') {   // most recent COMPLETE Saturday→Friday week (Egypt week starts Saturday)
    const end = addDays(y, -((dow(y) - 5 + 7) % 7))   // last Friday on/before yesterday
    return { start: addDays(end, -6), end }            // Saturday six days earlier
  }
  if (p === 'mtd') return { start: y.slice(0, 8) + '01', end: y }   // 1st of yesterday's month → yesterday
  const d = new Date()                // previous full calendar month
  const prev = `${d.getFullYear()}-${String(d.getMonth() === 0 ? 12 : d.getMonth()).padStart(2, '0')}`
  const ym = d.getMonth() === 0 ? `${d.getFullYear() - 1}-12` : prev
  return monthBounds(ym)
}
const SEV = {
  critical: 'bg-red-50 text-red-700 border-red-200',
  warning:  'bg-amber-50 text-amber-700 border-amber-200',
  info:     'bg-blue-50 text-blue-700 border-blue-200',
}

// Rule category labels (AR) — matches InsightRule.category choices.
const CAT_LABELS = {
  coverage: '🧭 تغطية البيانات', volume: '📊 حجم المبيعات', mix: '🧴 مزيج المنتجات',
  discount: '🏷️ الخصومات', comparison: '📈 مقارنات', highlight: '🏆 إنجازات',
}
const SEV_LABELS = { critical: 'حرج', warning: 'تنبيه', info: 'معلومة' }
const PERIOD_KEYS = ['day', 'week', 'month']
// Per-rule hint: what the threshold number means + its unit (empty = rule has no tunable threshold).
const THRESHOLD_HINTS = {
  branch_vs_prev: 'انخفاض مبيعات الفرع بنسبة ٪ عن الفترة السابقة',
  salesperson_no_beauty: 'حد أدنى لمبيعات المسئول (ج.م) حتى يُحتسب',
  salesperson_below_avg: 'المبيعات أقل من ٪ من متوسط المسئول',
  high_discount: 'خصم السطر ≥ ٪ (نقدى/توصيل)',
  high_discount_regular: 'خصم السطر ≥ ٪ (عميل دائم)',
  bulk_sale: 'قيمة الفاتورة النقدية ≥ (ج.م)',
  bulk_cash_ranking: 'حد الفاتورة النقدية الكبيرة (ج.م)',
  below_cost_sale: 'خسارة السطر ≥ (ج.م)',
  branch_high_returns: 'المرتجعات ≥ ٪ من المبيعات',
  branch_margin_drop: 'تراجع الهامش ≥ (نقاط ٪)',
  salesperson_over_discount: 'متوسط خصم المسئول ≥ ٪ (نقدى/توصيل)',
  salesperson_over_discount_regular: 'متوسط خصم المسئول ≥ ٪ (عميل دائم)',
  salesperson_regular_share: 'نسبة عميل دائم من مبيعات المسئول النقدية ≥ ٪',
  purchase_category_mix: 'اعتماد على المخازن الصغيرة ≥ ٪',
  supplier_return_spike: 'مرتجعات الموردين ≥ (ج.م)',
  stock_variance: 'فروق الجرد ≥ (عدد)',
  stockout_fastmovers: 'نفاد أصناف تبيع ≥ (وحدة/شهر)',
  dead_stock: 'قيمة المخزون الراكد ≥ (ج.م)',
  // purchasing
  hq_purchase_trend: 'تغيّر مشتريات HQ ≥ ٪ (عرض فقط)',
  purchase_price_creep: 'ارتفاع سعر شراء الصنف ≥ ٪',
  purchase_thin_margin: 'هامش الشراء أقل من ٪',
  buyer_small_warehouse: 'نسبة مشتريات المشترى من مستودعات صغيرة ≥ ٪',
  supplier_concentration: 'حصة أكبر مورد من مشتريات HQ ≥ ٪',
  branch_local_purchase: 'قيمة المشتريات المحلية للفرع ≥ (ج.م)',
  branch_small_warehouse: 'نسبة مشتريات الفرع من مستودعات صغيرة ≥ ٪',
  patient_repurchase_volume: 'قيمة الشراء من المرضى ≥ (ج.م)',
  branch_purchase_profile: 'حد أدنى لمشتريات الفرع لعرض القسم (ج.م)',
  supplier_scorecard: 'نسبة المرتجعات لوضع المورد بقائمة المتابعة ٪',
  // salesperson
  salesperson_basket: 'أقل من (صنف/فاتورة) للمسئول',
  salesperson_beauty_attach: 'منتج تجميل في أقل من ٪ من فواتيره',
  salesperson_return_rate: 'مرتجعات المسئول ≥ ٪ من مبيعاته',
  salesperson_customer_concentration: 'حصة أكبر عميل من مبيعات المسئول ≥ ٪',
  // sales boosting + abuse
  branch_basket: 'أقل من (صنف/فاتورة) للفرع',
  discount_to_one_customer: 'حصة عميل واحد من خصومات المسئول ≥ ٪',
  buy_vs_sell_imbalance: 'مبيعات الصنف أقل من ٪ من قيمة شرائه',
  wash_sale: 'نسبة المُرتجع من المُباع لنفس العميل/الصنف ≥ ٪',
  // target achievement (needs committed forecast targets for the month)
  branch_target_achievement: 'تنبيه إذا حقّق الفرع أقل من ٪ من هدفه',
  salesperson_target_achievement: 'تنبيه إذا حقّق المسئول أقل من ٪ من هدفه',
}

export default function InsightsPage() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canRun = ['admin', 'supervisor', 'purchasing', 'quality_manager'].includes(user?.role)
  const canEditRules = ['admin', 'supervisor'].includes(user?.role)   // matches InsightRuleViewSet._guard
  const [view, setView] = useState('reports')                         // 'reports' | 'rules'
  const [domain, setDomain] = useState('sales')                       // 'sales' | 'purchasing'
  const [period, setPeriod] = useState('day')
  const [selId, setSelId] = useState(null)
  const [range, setRange] = useState(() => defaultRange('day'))
  const yISO = addDays(isoToday(), -1)

  const changePeriod = (p) => { setPeriod(p); setRange(defaultRange(p)) }
  const span = daysBetween(range.start, range.end)          // inclusive day count
  const sameMonth = range.start.slice(0, 7) === range.end.slice(0, 7)
  const spanOk = period === 'day' ? span === 1
    : period === 'week' ? span === 7
    : period === 'mtd' ? (range.start.endsWith('-01') && sameMonth && span >= 1 && span <= 31)
    : span >= 1 && span <= 31

  const { data: reports = [], isLoading } = useQuery({
    queryKey: ['insight-reports', period, domain],
    queryFn: () => insightsApi.reports({ period, domain }).then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const gen = useMutation({
    mutationFn: () => insightsApi.generate({ period, domain, start: range.start, end: range.end }),
    onSuccess: (r) => { setSelId(r.data.id); qc.invalidateQueries({ queryKey: ['insight-reports'] }) },
  })

  return (
    <div className="p-6 max-w-[1200px] mx-auto" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">📋 التقارير السردية</h1>
          <p className="text-sm text-gray-500 mt-0.5">سرد تلقائي لأداء الفروع ومسئولي البيع — عربي / English</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {view === 'reports' && (
            <div className="flex rounded-lg bg-gray-100 p-0.5">
              <button onClick={() => { setDomain('sales'); setSelId(null) }}
                className={`px-3 py-1.5 text-sm rounded-md ${domain === 'sales' ? 'bg-white shadow font-bold text-gray-900' : 'text-gray-500'}`}>🧾 المبيعات</button>
              <button onClick={() => { setDomain('purchasing'); setSelId(null) }}
                className={`px-3 py-1.5 text-sm rounded-md ${domain === 'purchasing' ? 'bg-white shadow font-bold text-gray-900' : 'text-gray-500'}`}>📦 المشتريات والتموين</button>
            </div>
          )}
          {canEditRules && (
            <div className="flex rounded-lg bg-gray-100 p-0.5">
              <button onClick={() => setView('reports')}
                className={`px-3 py-1.5 text-sm rounded-md ${view === 'reports' ? 'bg-white shadow font-bold text-gray-900' : 'text-gray-500'}`}>📋 التقارير</button>
              <button onClick={() => setView('rules')}
                className={`px-3 py-1.5 text-sm rounded-md ${view === 'rules' ? 'bg-white shadow font-bold text-gray-900' : 'text-gray-500'}`}>⚙️ القواعد والحدود</button>
            </div>
          )}

          {view === 'reports' && (<>
          <div className="flex rounded-lg bg-gray-100 p-0.5">
            {Object.entries(PERIODS).map(([k, v]) => (
              <button key={k} onClick={() => changePeriod(k)}
                className={`px-3 py-1.5 text-sm rounded-md ${period === k ? 'bg-white shadow font-bold text-gray-900' : 'text-gray-500'}`}>{v}</button>
            ))}
          </div>

          {canRun && period === 'day' && (
            <input type="date" value={range.start} max={yISO}
              onChange={e => setRange({ start: e.target.value, end: e.target.value })}
              className="input-field !w-auto !py-1 text-sm" />
          )}

          {canRun && period === 'mtd' && (
            <div className="flex items-center gap-1 text-sm text-gray-500">
              <span className="text-xs">من {range.start} حتى</span>
              <input type="date" value={range.end} max={yISO} min={range.end.slice(0, 8) + '01'}
                onChange={e => setRange({ start: e.target.value.slice(0, 8) + '01', end: e.target.value })}
                className="input-field !w-auto !py-1 text-sm" />
              <span className="text-[11px] text-gray-400">({span} يوم)</span>
            </div>
          )}

          {canRun && period === 'week' && (
            <div className="flex items-center gap-1 text-sm text-gray-500">
              <span className="text-xs">من</span>
              <input type="date" value={range.start} max={yISO}
                onChange={e => setRange({ start: e.target.value, end: addDays(e.target.value, 6) })}
                className="input-field !w-auto !py-1 text-sm" />
              <span className="text-xs">إلى</span>
              <input type="date" value={range.end} max={yISO}
                onChange={e => setRange({ start: addDays(e.target.value, -6), end: e.target.value })}
                className="input-field !w-auto !py-1 text-sm" />
              <span className="text-[11px] text-gray-400">(7 أيام)</span>
            </div>
          )}

          {canRun && period === 'month' && (
            <div className="flex flex-wrap items-center gap-1 text-sm text-gray-500">
              <input type="month" value={range.start.slice(0, 7)} max={isoToday().slice(0, 7)}
                onChange={e => setRange(monthBounds(e.target.value))}
                className="input-field !w-auto !py-1 text-sm" title="اختر شهراً كاملاً" />
              <span className="text-xs">أو من</span>
              <input type="date" value={range.start} max={yISO}
                onChange={e => setRange(r => ({ start: e.target.value, end: daysBetween(e.target.value, r.end) > 31 || r.end < e.target.value ? addDays(e.target.value, 30) : r.end }))}
                className="input-field !w-auto !py-1 text-sm" />
              <span className="text-xs">إلى</span>
              <input type="date" value={range.end} max={yISO}
                onChange={e => setRange(r => ({ start: daysBetween(r.start, e.target.value) > 31 || e.target.value < r.start ? addDays(e.target.value, -30) : r.start, end: e.target.value }))}
                className="input-field !w-auto !py-1 text-sm" />
              <span className={`text-[11px] ${spanOk ? 'text-gray-400' : 'text-red-500'}`}>({span} يوم)</span>
            </div>
          )}

          {canRun && (
            <button onClick={() => gen.mutate()} disabled={gen.isPending || !spanOk} className="btn-primary text-sm disabled:opacity-40"
              title={spanOk ? '' : 'المدة غير صالحة'}>
              {gen.isPending ? 'جارٍ التوليد…' : '⚙️ توليد التقرير'}
            </button>
          )}
          </>)}
        </div>
      </div>

      {view === 'rules' ? <RulesEditor /> : (
      <div className="grid md:grid-cols-[260px_1fr] gap-4">
        <div className="space-y-2">
          {isLoading ? <div className="text-gray-400 text-sm py-8 text-center">جارٍ التحميل…</div>
            : reports.length === 0 ? <div className="text-gray-400 text-sm py-8 text-center">لا توجد تقارير</div>
            : reports.map(r => (
              <button key={r.id} onClick={() => setSelId(r.id)}
                className={`w-full text-right p-3 rounded-xl border transition ${selId === r.id ? 'border-blue-400 bg-blue-50/40' : 'border-gray-100 bg-white hover:border-gray-200'}`}>
                <div className="flex items-center justify-between">
                  <span className="font-bold text-gray-800 text-sm">{r.period_start}{r.period_start !== r.period_end ? ` → ${r.period_end}` : ''}</span>
                  <span className="text-[11px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{r.findings_count} ملاحظة</span>
                </div>
                <div className="text-[11px] text-gray-400 mt-0.5">{PERIODS[r.period_type]}{r.sent_at ? ' · أُرسل ✓' : ''}</div>
              </button>
            ))}
        </div>

        <div>
          {selId ? <ReportView id={selId} />
            : <div className="text-gray-400 text-sm py-16 text-center border border-dashed border-gray-200 rounded-2xl">اختر تقريراً لعرضه — أو ولّد تقريراً جديداً</div>}
        </div>
      </div>
      )}
    </div>
  )
}

// ── Rules & thresholds editor (admin/supervisor) ──────────────────────────────
function RulesEditor() {
  const qc = useQueryClient()
  const [drafts, setDrafts] = useState({})       // id → { threshold, enabled, periods }
  const [savedId, setSavedId] = useState(null)
  const { data: rules = [], isLoading } = useQuery({
    queryKey: ['insight-rules'],
    queryFn: () => insightsApi.rules().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const save = useMutation({
    mutationFn: ({ id, data }) => insightsApi.updateRule(id, data),
    onSuccess: (_r, v) => {
      setSavedId(v.id); setTimeout(() => setSavedId(s => (s === v.id ? null : s)), 1500)
      setDrafts(d => { const n = { ...d }; delete n[v.id]; return n })
      qc.invalidateQueries({ queryKey: ['insight-rules'] })
    },
  })

  const draftOf = (r) => drafts[r.id] || { threshold: r.threshold, enabled: r.enabled, periods: r.periods }
  const setDraft = (r, patch) => setDrafts(d => ({ ...d, [r.id]: { ...draftOf(r), ...patch } }))
  const isDirty = (r) => {
    const d = drafts[r.id]; if (!d) return false
    return String(d.threshold ?? '') !== String(r.threshold ?? '') || d.enabled !== r.enabled || d.periods !== r.periods
  }
  const togglePeriod = (r, p) => {
    const cur = draftOf(r).periods.split(',').filter(Boolean)
    const next = cur.includes(p) ? cur.filter(x => x !== p) : [...cur, p]
    setDraft(r, { periods: PERIOD_KEYS.filter(k => next.includes(k)).join(',') })
  }

  if (isLoading) return <div className="text-gray-400 text-sm py-16 text-center">جارٍ تحميل القواعد…</div>

  const byCat = {}
  rules.forEach(r => { (byCat[r.category] = byCat[r.category] || []).push(r) })
  const order = ['coverage', 'volume', 'mix', 'discount', 'comparison', 'highlight']
  const cats = [...order.filter(c => byCat[c]), ...Object.keys(byCat).filter(c => !order.includes(c))]

  return (
    <div className="space-y-5">
      <div className="text-sm text-gray-500 bg-blue-50/60 border border-blue-100 rounded-xl p-3">
        عدّل الحد (القيمة) الذي تُطلق عنده كل قاعدة ملاحظة، فعّل أو أوقف القاعدة، أو اختر الفترات التي تعمل بها.
        الحد يختلف معناه لكل قاعدة (٪ أو ج.م أو عدد) — الشرح بجانب كل قاعدة. التغييرات تُطبَّق على التقارير الجديدة.
      </div>

      {cats.map(cat => (
        <div key={cat} className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
          <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100 font-bold text-gray-700 text-sm">{CAT_LABELS[cat] || cat}</div>
          <div className="divide-y divide-gray-50">
            {byCat[cat].map(r => {
              const d = draftOf(r); const dirty = isDirty(r); const hasThr = r.threshold !== null
              return (
                <div key={r.id} className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
                  <label className="flex items-center gap-2 cursor-pointer min-w-[190px]">
                    <input type="checkbox" checked={d.enabled} onChange={e => setDraft(r, { enabled: e.target.checked })}
                      className="w-4 h-4 accent-emerald-600" />
                    <span className={`text-sm font-bold ${d.enabled ? 'text-gray-800' : 'text-gray-400 line-through'}`}>{r.name_ar}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${SEV[r.severity] || ''}`}>{SEV_LABELS[r.severity] || r.severity}</span>
                  </label>

                  <div className="flex items-center gap-2 min-w-[240px] flex-1">
                    {hasThr ? (
                      <>
                        <input type="number" step="any" value={d.threshold ?? ''}
                          onChange={e => setDraft(r, { threshold: e.target.value === '' ? null : e.target.value })}
                          className="input-field !w-28 !py-1 text-sm text-left" dir="ltr" />
                        <span className="text-[11px] text-gray-400">{THRESHOLD_HINTS[r.code] || ''}</span>
                      </>
                    ) : (
                      <span className="text-[11px] text-gray-400">قاعدة كشف/ترتيب — لا يوجد حد قابل للضبط</span>
                    )}
                  </div>

                  <div className="flex items-center gap-1">
                    {PERIOD_KEYS.map(p => {
                      const on = d.periods.split(',').includes(p)
                      return (
                        <button key={p} onClick={() => togglePeriod(r, p)}
                          className={`px-2 py-0.5 text-[11px] rounded-md border ${on ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-gray-50 text-gray-400 border-gray-200'}`}>
                          {PERIODS[p]}</button>
                      )
                    })}
                  </div>

                  <button
                    onClick={() => save.mutate({ id: r.id, data: { threshold: d.threshold, enabled: d.enabled, periods: d.periods } })}
                    disabled={!dirty || save.isPending}
                    className={`text-xs px-3 py-1 rounded-lg ${savedId === r.id ? 'bg-emerald-100 text-emerald-700'
                      : dirty ? 'bg-emerald-600 text-white hover:bg-emerald-700' : 'bg-gray-100 text-gray-400'} disabled:cursor-default`}>
                    {savedId === r.id ? '✓ حُفظ' : 'حفظ'}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

const SCOPES = { chain: '🏢 الشبكة', branch: '🏬 فرع', salesperson: '👤 مسئول بيع' }

function ReportView({ id }) {
  const [lang, setLang] = useState('ar')
  const [copied, setCopied] = useState(false)
  const [copiedF, setCopiedF] = useState(false)
  const [scopeType, setScopeType] = useState('chain')
  const [scopeKey, setScopeKey] = useState('')
  const [spBranch, setSpBranch] = useState('')   // branch filter for the salesperson picker

  const { data: scopes } = useQuery({ queryKey: ['insight-scopes', id], queryFn: () => insightsApi.scopes(id).then(r => r.data) })
  const needsKey = scopeType !== 'chain'

  // Salesperson picker aligned to branch: a branch filter + the reps of that branch.
  const allSp = scopes?.salespeople || []
  const spBranchOpts = Array.from(new Map(allSp.filter(s => s.branch_code)
    .map(s => [s.branch_code, s.branch_name])).entries())   // [[code, name], …]
  const visibleSp = spBranch ? allSp.filter(s => s.branch_code === spBranch) : allSp
  // disambiguate duplicate rep names within the visible list (same name, different usercode/branch)
  const nameCount = visibleSp.reduce((m, s) => (m[s.name] = (m[s.name] || 0) + 1, m), {})
  const spLabel = (s) => {
    let l = s.name
    if (!spBranch && s.branch_name) l += ` — ${s.branch_name}`
    if (nameCount[s.name] > 1) l += ` [${s.key}]`
    return l
  }
  const list = scopeType === 'branch' ? (scopes?.branches || []) : scopeType === 'salesperson' ? visibleSp : []

  const { data: rep, isFetching } = useQuery({
    queryKey: ['insight-scoped', id, scopeType, scopeKey],
    queryFn: () => insightsApi.scoped(id, { type: scopeType, key: scopeKey }).then(r => r.data),
    enabled: !needsKey || !!scopeKey,
  })

  const changeScope = (t) => {
    setScopeType(t); setSpBranch('')
    if (t === 'chain') setScopeKey('')
    else if (t === 'branch') setScopeKey(scopes?.branches?.[0]?.key || '')
    else setScopeKey(allSp?.[0]?.key || '')
  }
  const changeSpBranch = (code) => {
    setSpBranch(code)
    const next = code ? allSp.filter(s => s.branch_code === code) : allSp
    setScopeKey(next?.[0]?.key || '')
  }

  const text = rep ? (lang === 'ar' ? rep.narrative_ar : rep.narrative_en) : ''
  const copy = () => { navigator.clipboard?.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }
  const findingsText = (rep?.findings || []).map(f => '• ' + (lang === 'ar' ? f.message_ar : f.message_en)).join('\n')
  const copyFindings = () => { navigator.clipboard?.writeText(findingsText); setCopiedF(true); setTimeout(() => setCopiedF(false), 1500) }

  return (
    <div className="space-y-4">
      {/* ── scope selector: whole chain / one branch / one salesperson ── */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg bg-gray-100 p-0.5 text-sm">
          {Object.entries(SCOPES).map(([k, v]) => (
            <button key={k} onClick={() => changeScope(k)}
              className={`px-3 py-1.5 rounded-md ${scopeType === k ? 'bg-white shadow font-bold text-gray-900' : 'text-gray-500'}`}>{v}</button>
          ))}
        </div>
        {scopeType === 'salesperson' && spBranchOpts.length > 0 && (
          <select value={spBranch} onChange={e => changeSpBranch(e.target.value)} className="input-field !w-auto !py-1 text-sm">
            <option value="">كل الفروع</option>
            {spBranchOpts.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </select>
        )}
        {needsKey && (
          list.length ? (
            <select value={scopeKey} onChange={e => setScopeKey(e.target.value)} className="input-field !w-auto !py-1 text-sm">
              {list.map(x => <option key={x.key} value={x.key}>{scopeType === 'salesperson' ? spLabel(x) : x.name}</option>)}
            </select>
          ) : <span className="text-xs text-gray-400">لا توجد ملاحظات على هذا المستوى في هذا التقرير</span>
        )}
      </div>

      {needsKey && !scopeKey ? null : !rep ? (
        <div className="text-gray-400 text-sm py-8 text-center">{isFetching ? 'جارٍ التحميل…' : 'لا توجد بيانات'}</div>
      ) : (<>
      <div className="bg-white rounded-2xl border border-gray-100 p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex rounded-lg bg-gray-100 p-0.5 text-sm">
            <button onClick={() => setLang('ar')} className={`px-3 py-1 rounded-md ${lang === 'ar' ? 'bg-white shadow font-bold' : 'text-gray-500'}`}>عربي</button>
            <button onClick={() => setLang('en')} className={`px-3 py-1 rounded-md ${lang === 'en' ? 'bg-white shadow font-bold' : 'text-gray-500'}`}>English</button>
          </div>
          <button onClick={copy} className="text-sm px-3 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">
            {copied ? '✓ نُسخ' : '📋 نسخ (واتساب)'}
          </button>
        </div>
        <pre dir={lang === 'ar' ? 'rtl' : 'ltr'}
          className="whitespace-pre-wrap font-sans text-[15px] leading-8 text-gray-800 bg-gray-50 rounded-xl p-4 max-h-[60vh] overflow-y-auto">
          {text || (lang === 'ar' ? 'لا يوجد سرد لهذا المستوى.' : 'No narrative for this scope.')}
        </pre>
      </div>

      {rep.findings?.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-100 p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="font-bold text-gray-800 text-sm">الملاحظات ({rep.findings.length})</div>
            <button onClick={copyFindings} className="text-xs px-3 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-700">
              {copiedF ? '✓ نُسخ' : '📋 نسخ الملاحظات'}
            </button>
          </div>
          <div className="space-y-1.5">
            {rep.findings.map(f => (
              <div key={f.id} className={`text-sm px-3 py-1.5 rounded-lg border ${SEV[f.severity] || 'bg-gray-50'}`}>
                {lang === 'ar' ? f.message_ar : f.message_en}
              </div>
            ))}
          </div>
        </div>
      )}
      </>)}
    </div>
  )
}
