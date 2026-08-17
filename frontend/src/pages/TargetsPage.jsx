/**
 * TargetsPage.jsx — /targets
 * Sales targets & goals with live attainment (actual vs target + pace).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { targetsApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'

const PACE = {
  ahead:  { label: 'متقدّم',  cls: 'bg-emerald-100 text-emerald-700' },
  behind: { label: 'متأخّر',  cls: 'bg-amber-100 text-amber-700' },
  met:    { label: 'تحقّق',   cls: 'bg-emerald-100 text-emerald-700' },
  missed: { label: 'لم يتحقق', cls: 'bg-red-100 text-red-700' },
}
const fmt = n => (Number(n) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })

export default function TargetsPage() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canEdit = ['admin', 'supervisor', 'purchasing'].includes(user?.role)
  const [showForm, setShowForm] = useState(false)

  const { data: targets = [], isLoading } = useQuery({
    queryKey: ['targets'],
    queryFn: () => targetsApi.list().then(r => Array.isArray(r.data) ? r.data : (r.data.results || [])),
  })
  const del = useMutation({
    mutationFn: (id) => targetsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['targets'] }),
  })

  return (
    <div className="p-6 max-w-5xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🎯 الأهداف البيعية</h1>
          <p className="text-sm text-gray-500 mt-0.5">حدّد الهدف وتابع التحقيق لحظياً مقابل المبيعات الفعلية</p>
        </div>
        {canEdit && (
          <button onClick={() => setShowForm(s => !s)} className="btn-primary text-sm">
            {showForm ? 'إغلاق' : '+ هدف جديد'}
          </button>
        )}
      </div>

      {showForm && canEdit && <TargetForm onDone={() => { setShowForm(false); qc.invalidateQueries({ queryKey: ['targets'] }) }} />}

      {isLoading ? (
        <div className="text-center py-16 text-gray-400">جارٍ التحميل…</div>
      ) : targets.length === 0 ? (
        <div className="text-center py-16 text-gray-400">لا توجد أهداف بعد</div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {targets.map(t => {
            const a = t.attainment || {}
            const pace = PACE[a.pace] || {}
            const pct = Math.min(a.pct || 0, 100)
            const isMoney = t.metric === 'net_revenue'
            return (
              <div key={t.id} className="bg-white rounded-2xl border border-gray-100 p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="font-bold text-gray-900 text-sm">{t.label || t.scope_label}</div>
                    <div className="text-xs text-gray-400">
                      {t.scope_label}{t.branch_name ? ` · ${t.branch_name}` : ''}{t.softech_user ? ` · مندوب ${t.softech_user}` : ''}{t.category_name ? ` · ${t.category_name}` : ''} · {t.metric_label}
                    </div>
                    <div className="text-[11px] text-gray-400 mt-0.5">{t.period_start} → {t.period_end} · باقٍ {a.days_left} يوم</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${pace.cls || 'bg-gray-100 text-gray-500'}`}>{pace.label || '—'}</span>
                    {canEdit && <button onClick={() => del.mutate(t.id)} className="text-gray-300 hover:text-red-500 text-xs">✕</button>}
                  </div>
                </div>
                <div className="flex items-baseline justify-between text-sm mb-1">
                  <span className="font-black text-gray-900">{fmt(a.actual)}{isMoney ? ' ج.م' : ''}</span>
                  <span className="text-gray-400 text-xs">من {fmt(a.target)}{isMoney ? ' ج.م' : ''} · {a.pct}%</span>
                </div>
                <div className="h-2.5 rounded-full bg-gray-100 overflow-hidden relative">
                  <div className={`h-full rounded-full ${a.pace === 'behind' || a.pace === 'missed' ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${pct}%` }} />
                  {/* expected-to-date marker */}
                  {a.target > 0 && (
                    <div className="absolute top-0 bottom-0 w-0.5 bg-gray-400" style={{ right: `${Math.min((a.expected_to_date / a.target) * 100, 100)}%` }} title="المتوقّع حتى اليوم" />
                  )}
                </div>
                <div className="text-[11px] text-gray-400 mt-1">المتوقّع حتى اليوم: {fmt(a.expected_to_date)}{isMoney ? ' ج.م' : ''}</div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function TargetForm({ onDone }) {
  const [f, setF] = useState({
    label: '', scope_type: 'branch', branch: '', softech_user: '',
    metric: 'net_revenue', period_start: '', period_end: '', target_value: '',
  })
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })
  const create = useMutation({ mutationFn: (data) => targetsApi.create(data), onSuccess: onDone })
  const set = (k, v) => setF(s => ({ ...s, [k]: v }))

  function submit() {
    const payload = {
      label: f.label, scope_type: f.scope_type, metric: f.metric,
      period_start: f.period_start, period_end: f.period_end,
      target_value: f.target_value,
      branch: f.scope_type === 'branch' ? f.branch || null : null,
      softech_user: f.scope_type === 'salesperson' ? f.softech_user : '',
    }
    create.mutate(payload)
  }
  const valid = f.period_start && f.period_end && f.target_value &&
    (f.scope_type !== 'branch' || f.branch) && (f.scope_type !== 'salesperson' || f.softech_user)

  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4 mb-4 grid gap-2 md:grid-cols-3">
      <input className="input-field" placeholder="اسم الهدف" value={f.label} onChange={e => set('label', e.target.value)} />
      <select className="input-field" value={f.scope_type} onChange={e => set('scope_type', e.target.value)}>
        <option value="chain">الشبكة كاملة</option>
        <option value="branch">فرع</option>
        <option value="salesperson">مندوب</option>
      </select>
      <select className="input-field" value={f.metric} onChange={e => set('metric', e.target.value)}>
        <option value="net_revenue">صافي المبيعات</option>
        <option value="orders">عدد الفواتير</option>
      </select>
      {f.scope_type === 'branch' && (
        <select className="input-field" value={f.branch} onChange={e => set('branch', e.target.value)}>
          <option value="">اختر الفرع…</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
        </select>
      )}
      {f.scope_type === 'salesperson' && (
        <input className="input-field" placeholder="كود المندوب (SOFTECH)" value={f.softech_user} onChange={e => set('softech_user', e.target.value)} />
      )}
      <input className="input-field" type="date" value={f.period_start} onChange={e => set('period_start', e.target.value)} />
      <input className="input-field" type="date" value={f.period_end} onChange={e => set('period_end', e.target.value)} />
      <input className="input-field" type="number" placeholder="القيمة المستهدفة" value={f.target_value} onChange={e => set('target_value', e.target.value)} />
      <button onClick={submit} disabled={!valid || create.isPending} className="btn-primary text-sm disabled:opacity-40">
        {create.isPending ? 'جارٍ الحفظ…' : 'حفظ الهدف'}
      </button>
    </div>
  )
}
