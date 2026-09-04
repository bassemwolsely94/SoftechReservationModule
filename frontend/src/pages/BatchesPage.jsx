/**
 * BatchesPage — FEFO Batch Management + Near-Expiry Dashboard
 * Covers: batch list, near-expiry KPIs, active alerts, quarantine action
 */
import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { batchesApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── date helpers ──────────────────────────────────────────────────────────────
const _iso = (d) => d.toISOString().slice(0, 10)
// Default ENTERED-EXPIRY window: first day of this month → end of +3 months
// (a near-term "what's expiring soon" horizon; the user narrows it as needed).
function _defaultExpiryFrom() {
  const d = new Date(); d.setDate(1)
  return _iso(d)
}
function _defaultExpiryTo() {
  const d = new Date(); d.setMonth(d.getMonth() + 4, 0)   // last day of +3 months
  return _iso(d)
}
function _fmtDate(s) {
  return s ? new Date(s).toLocaleDateString('ar-EG') : '—'
}

function KpiCard({ label, value, sub, color = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value ?? '—'}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function QuarantineModal({ batch, onClose }) {
  const qc    = useQueryClient()
  const [reason, setReason] = useState('')
  const [err, setErr]       = useState(null)

  const mutation = useMutation({
    mutationFn: () => batchesApi.quarantine(batch.id, reason),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['batches'] }); onClose() },
    onError:   e  => setErr(e.response?.data?.detail || 'حدث خطأ'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-1">عزل دفعة</h3>
        <p className="text-sm text-gray-500 mb-4">
          {batch.item_name} — دفعة {batch.batch_number}
        </p>
        <textarea
          value={reason} onChange={e => setReason(e.target.value)}
          placeholder="سبب العزل (مطلوب)..."
          className="w-full border rounded-lg p-3 text-sm resize-none h-24 mb-4"
        />
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !reason.trim()}
            className="px-5 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {mutation.isPending ? 'جاري...' : 'تأكيد العزل'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Purchase-Expiry Physical Audit tab ────────────────────────────────────────
function PurchaseExpiryAuditTab() {
  const navigate = useNavigate()
  const user     = useAuthStore(s => s.user)
  const isAdmin  = ['admin', 'supervisor'].includes(user?.role)

  const [from, setFrom]           = useState(_defaultExpiryFrom())
  const [to, setTo]               = useState(_defaultExpiryTo())
  const [branch, setBranch]       = useState('')          // '' = all branches
  const [onlyInStock, setOnly]    = useState(true)
  const [rows, setRows]           = useState(null)
  const [err, setErr]             = useState(null)

  // Client-side filter/sort (operate on the fetched rows — no SOFTECH re-hit)
  const [search, setSearch]       = useState('')
  const [importedOnly, setImp]    = useState(false)
  const [minVar, setMinVar]       = useState('')
  const [minQ, setMinQ]           = useState('')
  const [sortKey, setSortKey]     = useState('value_at_risk')

  const displayRows = useMemo(() => {
    if (!rows) return null
    let out = rows.filter(r => {
      if (importedOnly && !r.is_imported) return false
      if (minVar && (r.value_at_risk || 0) < Number(minVar)) return false
      if (minQ && (r.current_qty || 0) < Number(minQ)) return false
      if (search) {
        const q = search.toLowerCase()
        if (!((r.item_name || '').toLowerCase().includes(q) ||
              (r.item_code || '').includes(q))) return false
      }
      return true
    })
    const num = (k) => (a, b) => (b[k] || 0) - (a[k] || 0)   // desc, nulls last
    const cmp = {
      value_at_risk: num('value_at_risk'),
      current_qty:   num('current_qty'),
      unit_cost:     num('unit_cost'),
      retail_value:  num('retail_value'),
      entry_count:   num('entry_count'),
      expiry: (a, b) => (a.earliest_entered_expiry || '9999').localeCompare(b.earliest_entered_expiry || '9999'),
    }[sortKey] || num('value_at_risk')
    return [...out].sort(cmp)
  }, [rows, importedOnly, minVar, minQ, search, sortKey])

  const totalVar = useMemo(
    () => (displayRows || []).reduce((s, r) => s + (r.value_at_risk || 0), 0),
    [displayRows],
  )

  const { data: branchesData } = useQuery({
    queryKey: ['branches', 'all-for-audit'],
    queryFn:  () => branchesApi.list().then(r => r.data),
  })
  const branches = branchesData?.results || branchesData || []

  const { data: runsData } = useQuery({
    queryKey: ['batches', 'purchase-expiry-runs'],
    queryFn:  () => batchesApi.purchaseExpiryRuns().then(r => r.data),
    refetchInterval: (q) => {
      const list = q.state.data?.results || q.state.data || []
      return list.some(r => r.status === 'running') ? 4000 : false
    },
  })
  const runs      = runsData?.results || runsData || []
  const lastRun   = runs[0]
  const isRunning = runs.some(r => r.status === 'running')

  const candidates = useMutation({
    mutationFn: () => batchesApi.purchaseExpiryCandidates({
      from, to,
      branches: branch ? [branch] : undefined,
      only_in_stock: onlyInStock,
    }).then(r => r.data),
    onSuccess: (data) => { setRows(data.items || []); setErr(null) },
    onError:   (e)    => setErr(e.response?.data?.detail || 'تعذّر توليد التقرير'),
  })

  const sync = useMutation({
    mutationFn: () => batchesApi.purchaseExpirySync({ from, to, branch: branch || undefined }),
    onError:   (e) => setErr(e.response?.data?.detail || 'تعذّر بدء المزامنة'),
  })

  const spawn = useMutation({
    mutationFn: () => batchesApi.purchaseExpirySpawnCount({ branch, from, to }).then(r => r.data),
    onSuccess: (data) => navigate(`/stock-count?session=${data.session_id}`),
    onError:   (e) => setErr(e.response?.data?.detail || 'تعذّر إنشاء جلسة الجرد'),
  })

  return (
    <div>
      {/* Explanation */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-5 text-sm text-blue-900 leading-relaxed">
        يعرض هذا التقرير الأصناف <b>الموجودة بالمخزون حاليًا</b> التي سجّل لها
        <b> موزّع رئيسي / مصنع</b> — عند الشراء في <b>أي وقت</b> —
        <b> تاريخ صلاحية يقع ضمن الفترة المحددة أدناه</b> (نطاق الصلاحية، وليس تاريخ الشراء)،
        لسحبها ماديًا والتحقق من صلاحيتها الفعلية على الرف.
        <span className="text-blue-700"> (لا يُشترط أن يحمل المخزون الحالي نفس هذه الصلاحية — البيان مجرد إشارة للفحص.)</span>
      </div>

      {/* Backfill status + admin sync */}
      <div className="flex flex-wrap items-center gap-3 mb-4 bg-white rounded-xl border border-gray-200 p-4">
        <div className="text-sm text-gray-600 flex-1">
          {lastRun ? (
            <>آخر مزامنة: <b>{_fmtDate(lastRun.started_at)}</b> —{' '}
              {lastRun.status === 'running' ? <span className="text-amber-600">جارية…</span>
                : lastRun.status === 'success' ? <span className="text-green-700">ناجحة ({lastRun.lines_upserted?.toLocaleString('ar-EG')} سطر جديد، {lastRun.suppliers_count} مورد)</span>
                : <span className="text-red-600">فشلت</span>}
            </>
          ) : <span className="text-gray-400">لم تُنفّذ مزامنة بعد — شغّل المزامنة لجلب بيانات الشراء (٣ سنوات).</span>}
        </div>
        {isAdmin && (
          <button
            onClick={() => sync.mutate()}
            disabled={sync.isPending || isRunning}
            className="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
          >
            {sync.isPending || isRunning ? 'المزامنة جارية…' : '🔄 مزامنة بيانات الشراء (٣ سنوات)'}
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 mb-5">
        <label className="text-sm">
          <span className="block text-gray-500 mb-1">الصلاحية من</span>
          <input type="date" value={from} onChange={e => setFrom(e.target.value)}
                 className="border rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="text-sm">
          <span className="block text-gray-500 mb-1">الصلاحية إلى</span>
          <input type="date" value={to} onChange={e => setTo(e.target.value)}
                 className="border rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="text-sm">
          <span className="block text-gray-500 mb-1">الفرع</span>
          <select value={branch} onChange={e => setBranch(e.target.value)}
                  className="border rounded-lg px-3 py-2 text-sm min-w-[10rem]">
            <option value="">كل الفروع</option>
            {branches.map(b => (
              <option key={b.id} value={b.softech_branch_id}>
                {b.name_ar || b.display_name || b.softech_branch_id}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm flex items-center gap-2 pb-2">
          <input type="checkbox" checked={onlyInStock} onChange={e => setOnly(e.target.checked)} />
          <span className="text-gray-600">الموجود بالمخزون فقط</span>
        </label>
        <button
          onClick={() => candidates.mutate()}
          disabled={candidates.isPending || !from || !to}
          className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
        >
          {candidates.isPending ? 'جاري التحميل…' : 'توليد التقرير'}
        </button>
      </div>

      {err && <p className="text-red-600 text-sm mb-3">{err}</p>}

      {/* Results */}
      {rows === null ? (
        <div className="text-center py-14 text-gray-400">حدّد الفترة والفرع ثم اضغط «توليد التقرير».</div>
      ) : rows.length === 0 ? (
        <div className="text-center py-14 text-gray-400">لا توجد أصناف مطابقة للمعايير.</div>
      ) : (
        <>
          {/* Client-side filter + sort bar (no re-query) */}
          <div className="flex flex-wrap items-center gap-2 mb-3 bg-white rounded-xl border border-gray-200 p-3 text-sm">
            <input value={search} onChange={e => setSearch(e.target.value)}
                   placeholder="بحث بالاسم / الكود…"
                   className="border rounded-lg px-3 py-1.5 flex-1 min-w-[9rem]" />
            <label className="flex items-center gap-1 text-gray-600">
              <input type="checkbox" checked={importedOnly} onChange={e => setImp(e.target.checked)} />
              مستورد فقط
            </label>
            <input type="number" value={minVar} onChange={e => setMinVar(e.target.value)}
                   placeholder="أدنى قيمة خطر" className="border rounded-lg px-2 py-1.5 w-28" />
            <input type="number" value={minQ} onChange={e => setMinQ(e.target.value)}
                   placeholder="أدنى كمية" className="border rounded-lg px-2 py-1.5 w-24" />
            <select value={sortKey} onChange={e => setSortKey(e.target.value)}
                    className="border rounded-lg px-2 py-1.5">
              <option value="value_at_risk">ترتيب: الأكبر خسارة محتملة</option>
              <option value="current_qty">ترتيب: الأكبر كمية</option>
              <option value="unit_cost">ترتيب: الأغلى (تكلفة الوحدة)</option>
              <option value="retail_value">ترتيب: أعلى قيمة بيعية</option>
              <option value="expiry">ترتيب: الأقرب صلاحية مُدخَلة</option>
              <option value="entry_count">ترتيب: الأكثر إدخالات</option>
            </select>
          </div>

          <div className="flex items-center justify-between mb-3">
            <p className="text-sm text-gray-600">
              عدد الأصناف: <b>{displayRows.length}</b>
              <span className="mx-2 text-gray-300">·</span>
              إجمالي القيمة المعرضة للخطر: <b className="text-red-600">{Math.round(totalVar).toLocaleString('ar-EG')} ج</b>
            </p>
            <button
              onClick={() => spawn.mutate()}
              disabled={spawn.isPending || !branch}
              title={!branch ? 'اختر فرعًا لبدء جرد مادي' : ''}
              className="px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
            >
              {spawn.isPending ? 'جاري الإنشاء…' : '▶️ بدء جرد مادي لهذه الأصناف'}
            </button>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">كود</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">الصنف</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">الكمية</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">تكلفة الوحدة</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">قيمة معرّضة للخطر</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">المنشأ</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">الفروع</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">صلاحية مُدخَلة (من / إلى)</th>
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">إدخالات</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map(r => (
                  <tr key={r.item_code} className={`border-b border-gray-100 hover:bg-gray-50 ${r.has_entered_expiry_passed ? 'bg-red-50' : ''}`}>
                    <td className="px-3 py-3 font-mono text-xs text-gray-500">{r.item_code}</td>
                    <td className="px-3 py-3 font-medium">
                      {r.item_name || '—'}
                      {r.is_imported &&
                        <span className="mr-2 px-2 py-0.5 rounded-full text-xs bg-indigo-100 text-indigo-700">مستورد</span>}
                      {r.has_entered_expiry_passed &&
                        <span className="mr-2 px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">صلاحية مُدخَلة منتهية</span>}
                    </td>
                    <td className="px-3 py-3">{r.current_qty != null ? r.current_qty.toLocaleString('ar-EG') : '—'}</td>
                    <td className="px-3 py-3 text-gray-600">{r.unit_cost != null ? r.unit_cost.toLocaleString('ar-EG') : '—'}</td>
                    <td className="px-3 py-3 font-semibold text-red-600">{r.value_at_risk != null ? Math.round(r.value_at_risk).toLocaleString('ar-EG') : '—'}</td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{r.origin || '—'}</td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{(r.branches_in_stock || []).join('، ') || '—'}</td>
                    <td className="px-3 py-3 text-gray-700 text-xs">
                      {_fmtDate(r.earliest_entered_expiry)} → {_fmtDate(r.latest_entered_expiry)}
                    </td>
                    <td className="px-3 py-3">{r.entry_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}


export default function BatchesPage() {
  const [tab, setTab]           = useState('alerts')
  const [quarantineBatch, setQ] = useState(null)
  const [filters, setFilters]   = useState({ expiring_in_days: 180 })

  const { data: summary } = useQuery({
    queryKey: ['batches', 'near-expiry-summary'],
    queryFn:  () => batchesApi.nearExpirySummary({}).then(r => r.data),
  })

  const { data: alertsData, isLoading: alertsLoading } = useQuery({
    queryKey: ['batches', 'alerts'],
    queryFn:  () => batchesApi.alerts({}).then(r => r.data),
    enabled:  tab === 'alerts',
  })

  const { data: batchData, isLoading: batchLoading } = useQuery({
    queryKey: ['batches', 'list', filters],
    queryFn:  () => batchesApi.list(filters).then(r => r.data),
    enabled:  tab === 'list',
  })

  const alerts  = alertsData?.results || alertsData || []
  const batches = batchData?.results  || batchData  || []

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">إدارة الدفعات (FEFO)</h1>
        <p className="text-sm text-gray-500 mt-1">مراقبة انتهاء الصلاحية · نظام الصرف الأول انتهاء أولاً</p>
      </div>

      {/* KPI cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <KpiCard label="دفعات تنتهي خلال 30 يوم"  value={summary.lt_30?.batches}  sub={`${summary.lt_30?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`}  color="text-red-600" />
          <KpiCard label="دفعات تنتهي خلال 90 يوم"  value={summary.lt_90?.batches}  sub={`${summary.lt_90?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`}  color="text-amber-600" />
          <KpiCard label="دفعات تنتهي خلال 180 يوم" value={summary.lt_180?.batches} sub={`${summary.lt_180?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`} color="text-yellow-600" />
          <KpiCard label="قيمة البضاعة المعرضة للخطر" value={summary.total_at_risk_value != null ? `${Math.round(summary.total_at_risk_value).toLocaleString('ar-EG')} ج` : '—'} color="text-gray-700" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {[
          { key: 'alerts', label: '🚨 تنبيهات الانتهاء' },
          { key: 'list',   label: '📦 قائمة الدفعات'   },
          { key: 'audit',  label: '📅 تدقيق صلاحيات الشراء' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Alerts tab */}
      {tab === 'alerts' && (
        alertsLoading ? (
          <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <div className="text-4xl mb-3">✅</div>
            <p>لا توجد تنبيهات انتهاء صلاحية نشطة</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الفرع</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">رقم الدفعة</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">تاريخ الانتهاء</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الكمية</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الحد (أيام)</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map(a => (
                  <tr key={a.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{a.batch?.item_name || a.item_name || '—'}</td>
                    <td className="px-4 py-3 text-gray-500">{a.batch?.branch_name || '—'}</td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{a.batch?.batch_number || '—'}</td>
                    <td className="px-4 py-3 text-red-600 font-medium">
                      {a.batch?.expiry_date ? new Date(a.batch.expiry_date).toLocaleDateString('ar-EG') : '—'}
                    </td>
                    <td className="px-4 py-3">{a.batch?.current_qty ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-800">
                        {a.threshold_days} يوم
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Batch list tab */}
      {tab === 'list' && (
        <>
          <div className="flex gap-3 mb-4">
            <select
              value={filters.expiring_in_days}
              onChange={e => setFilters(f => ({ ...f, expiring_in_days: e.target.value }))}
              className="border rounded-lg px-3 py-2 text-sm"
            >
              <option value={30}>تنتهي خلال 30 يوم</option>
              <option value={90}>تنتهي خلال 90 يوم</option>
              <option value={180}>تنتهي خلال 180 يوم</option>
              <option value={365}>تنتهي خلال سنة</option>
            </select>
            <select
              value={filters.is_quarantined || ''}
              onChange={e => setFilters(f => ({ ...f, is_quarantined: e.target.value || undefined }))}
              className="border rounded-lg px-3 py-2 text-sm"
            >
              <option value="">الكل</option>
              <option value="false">غير معزول</option>
              <option value="true">في العزل</option>
            </select>
          </div>

          {batchLoading ? (
            <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
          ) : batches.length === 0 ? (
            <div className="text-center py-16 text-gray-400">لا توجد دفعات بهذه المعايير</div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الفرع</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">رقم الدفعة</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">تاريخ الانتهاء</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الكمية</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {batches.map(b => (
                    <tr key={b.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium">{b.item_name || b.item?.name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500">{b.branch_name || b.branch?.name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs">{b.batch_number}</td>
                      <td className="px-4 py-3 text-gray-700">
                        {b.expiry_date ? new Date(b.expiry_date).toLocaleDateString('ar-EG') : '—'}
                      </td>
                      <td className="px-4 py-3">{b.current_qty}</td>
                      <td className="px-4 py-3">
                        {b.is_quarantined ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">معزول</span>
                        ) : b.is_expired ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">منتهي</span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">نشط</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {!b.is_quarantined && !b.is_expired && (
                          <button
                            onClick={() => setQ(b)}
                            className="text-xs text-red-600 hover:underline"
                          >
                            عزل
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === 'audit' && <PurchaseExpiryAuditTab />}

      {quarantineBatch && <QuarantineModal batch={quarantineBatch} onClose={() => setQ(null)} />}
    </div>
  )
}
