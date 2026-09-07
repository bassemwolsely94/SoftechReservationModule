/**
 * ChequePlanningPage.jsx
 *
 * Post-dated cheque planning with Egyptian banking-day awareness.
 * Layout:
 *  Top row  : Treasury dashboard KPIs (outstanding, overdue, upcoming)
 *  Left col : Plan list with filters
 *  Right col: Plan detail / create form with instalment grid
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { chequesApi, branchesApi } from '../api/client'

// ── Status config ─────────────────────────────────────────────────────────────
const PLAN_STATUS = {
  draft:     { label: 'مسودة',    color: 'bg-gray-100 text-gray-700' },
  active:    { label: 'نشطة',    color: 'bg-green-100 text-green-700' },
  completed: { label: 'مكتملة',  color: 'bg-teal-100 text-teal-700' },
  cancelled: { label: 'ملغاة',   color: 'bg-red-100 text-red-600' },
}

const INST_STATUS = {
  pending:   { label: 'لم يُصدَر',       color: 'bg-gray-100 text-gray-600' },
  issued:    { label: 'صادر',            color: 'bg-blue-100 text-blue-700' },
  presented: { label: 'مُقدَّم للبنك',   color: 'bg-yellow-100 text-yellow-700' },
  cleared:   { label: 'تمّ الصرف',       color: 'bg-green-100 text-green-700' },
  bounced:   { label: 'ارتدّ / رُفض',    color: 'bg-red-100 text-red-700' },
  cancelled: { label: 'ملغي',            color: 'bg-red-50 text-red-400' },
}

const StatusBadge = ({ status, map }) => {
  const m = map[status] || { label: status, color: 'bg-gray-100 text-gray-500' }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>{m.label}</span>
  )
}

const fmt = (n) => n ? Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 }) : '0'
const fmtDate = (d) => d ? new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

// ── Treasury KPI strip ────────────────────────────────────────────────────────
function TreasuryStrip() {
  const { data, isLoading } = useQuery({
    queryKey: ['cheques-treasury'],
    queryFn: () => chequesApi.treasury().then(r => r.data),
    refetchInterval: 60000,
  })

  if (isLoading) return <div className="h-20 bg-gray-50 animate-pulse rounded-xl" />

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <KpiCard label="الخطط النشطة"       value={data?.active_plans_count ?? 0}     unit="" color="blue" />
      <KpiCard label="إجمالي المتبقي"     value={fmt(data?.total_outstanding)}        unit="ج.م" color="indigo" />
      <KpiCard label="شيكات خلال 30 يوم" value={data?.upcoming_30d_count ?? 0}      unit={`(${fmt(data?.upcoming_30d_amount)} ج.م)`} color="yellow" />
      <KpiCard label="شيكات متأخرة"       value={data?.overdue_count ?? 0}           unit={`(${fmt(data?.overdue_amount)} ج.م)`}  color="red" alert={data?.overdue_count > 0} />
    </div>
  )
}

function KpiCard({ label, value, unit, color, alert }) {
  const colors = {
    blue:   'from-blue-50 to-white border-blue-200 text-blue-700',
    indigo: 'from-indigo-50 to-white border-indigo-200 text-indigo-700',
    yellow: 'from-yellow-50 to-white border-yellow-200 text-yellow-700',
    red:    'from-red-50 to-white border-red-200 text-red-700',
  }
  return (
    <div className={`bg-gradient-to-br ${colors[color]} border rounded-xl p-4 relative`}>
      {alert && (
        <span className="absolute top-2 left-2 w-2 h-2 bg-red-500 rounded-full animate-ping" />
      )}
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${colors[color].split(' ').find(c => c.startsWith('text-'))}`}>{value}</p>
      {unit && <p className="text-xs text-gray-400 mt-0.5">{unit}</p>}
    </div>
  )
}

// ── Plan list ─────────────────────────────────────────────────────────────────
function PlanList({ selectedId, onSelect, onNew }) {
  const [statusFilter, setStatusFilter] = useState('')
  const [q, setQ] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['cheque-plans', statusFilter, q],
    queryFn: () => chequesApi.plans({ status: statusFilter || undefined, q: q || undefined })
      .then(r => r.data),
  })
  const plans = Array.isArray(data) ? data : (data?.results ?? [])

  return (
    <div className="flex flex-col h-full bg-white border-r border-gray-200">
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-bold text-gray-800">خطط الشيكات</h2>
          <button
            onClick={onNew}
            className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700"
          >
            + خطة جديدة
          </button>
        </div>
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="بحث بالاسم أو المستفيد..."
          className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-400"
          dir="rtl"
        />
      </div>

      {/* Status tabs */}
      <div className="flex border-b border-gray-200 bg-gray-50">
        {[
          { k: '', l: 'الكل' },
          { k: 'draft', l: 'مسودة' },
          { k: 'active', l: 'نشطة' },
          { k: 'completed', l: 'مكتملة' },
        ].map(t => (
          <button
            key={t.k}
            onClick={() => setStatusFilter(t.k)}
            className={`flex-1 py-2 text-xs font-medium ${
              statusFilter === t.k
                ? 'border-b-2 border-indigo-600 text-indigo-700 bg-white'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.l}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && <div className="p-4 text-center text-gray-400 text-sm">جارٍ التحميل...</div>}
        {!isLoading && plans.length === 0 && (
          <div className="p-6 text-center text-gray-400 text-sm">لا توجد خطط</div>
        )}
        {plans.map(p => (
          <button
            key={p.id}
            onClick={() => onSelect(p.id)}
            className={`w-full text-right px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
              selectedId === p.id ? 'bg-indigo-50 border-r-4 border-r-indigo-500' : ''
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-900 truncate">{p.title}</p>
                <p className="text-xs text-gray-500">{p.payee_name}</p>
                <p className="text-xs text-indigo-600 font-medium mt-0.5">
                  {fmt(p.total_amount)} ج.م — {p.cheque_count} شيك
                </p>
                {p.next_due_date && (
                  <p className="text-xs text-gray-400">
                    التالي: {fmtDate(p.next_due_date)}
                  </p>
                )}
              </div>
              <StatusBadge status={p.status} map={PLAN_STATUS} />
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Preview table ─────────────────────────────────────────────────────────────
function PreviewTable({ previewRows }) {
  if (!previewRows?.length) return null
  return (
    <div className="mt-4 border border-gray-200 rounded-lg overflow-hidden">
      <table className="w-full text-sm" dir="rtl">
        <thead className="bg-gray-50 text-xs text-gray-600">
          <tr>
            <th className="px-3 py-2 text-right">#</th>
            <th className="px-3 py-2 text-right">تاريخ الاستحقاق</th>
            <th className="px-3 py-2 text-right">المبلغ</th>
            <th className="px-3 py-2 text-right">تعديل</th>
          </tr>
        </thead>
        <tbody>
          {previewRows.map((row, i) => (
            <tr key={i} className={`border-t border-gray-100 ${row.adjusted ? 'bg-yellow-50' : ''}`}>
              <td className="px-3 py-2 text-gray-500">{row.instalment_no}</td>
              <td className="px-3 py-2 font-medium">{fmtDate(row.due_date)}</td>
              <td className="px-3 py-2 font-medium text-indigo-700">{fmt(row.amount)} ج.م</td>
              <td className="px-3 py-2">
                {row.adjusted ? (
                  <span className="text-xs text-yellow-700 bg-yellow-100 px-1.5 py-0.5 rounded">
                    ⚠️ تم تعديله من {fmtDate(row.nominal_date)}
                  </span>
                ) : (
                  <span className="text-xs text-green-600">✓</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Create form ───────────────────────────────────────────────────────────────
const EMPTY = {
  title: '', payee_name: '', bank_name: '', account_number: '',
  total_amount: '', reference_doc: '', notes: '',
  cheque_count: 1, first_due_date: '', interval_value: 1, interval_unit: 'months',
  branch: '',
}

function PlanForm({ onSave, onCancel }) {
  const qc = useQueryClient()
  const [form, setForm] = useState(EMPTY)
  const [previewRows, setPreviewRows] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const { data: branchesData } = useQuery({
    queryKey: ['branches-simple'],
    queryFn: () => branchesApi.list({ page_size: 100 }).then(r => r.data?.results ?? r.data),
  })
  const branches = Array.isArray(branchesData) ? branchesData : []

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handlePreview = async () => {
    if (!form.first_due_date || !form.total_amount || !form.cheque_count) return
    setPreviewLoading(true)
    try {
      const r = await chequesApi.preview({
        first_due_date: form.first_due_date,
        count: Number(form.cheque_count),
        total_amount: form.total_amount,
        interval_value: Number(form.interval_value),
        interval_unit: form.interval_unit,
      })
      setPreviewRows(r.data)
    } finally {
      setPreviewLoading(false)
    }
  }

  const createMutation = useMutation({
    mutationFn: (data) => chequesApi.createPlan(data),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['cheque-plans'] })
      qc.invalidateQueries({ queryKey: ['cheques-treasury'] })
      onSave(res.data.id)
    },
  })

  const handleSubmit = () => {
    createMutation.mutate({
      title: form.title,
      payee_name: form.payee_name,
      bank_name: form.bank_name,
      account_number: form.account_number,
      total_amount: form.total_amount,
      reference_doc: form.reference_doc,
      notes: form.notes,
      cheque_count: Number(form.cheque_count),
      first_due_date: form.first_due_date,
      interval_value: Number(form.interval_value),
      interval_unit: form.interval_unit,
      branch: form.branch ? Number(form.branch) : null,
    })
  }

  const canPreview = form.first_due_date && form.total_amount > 0 && form.cheque_count > 0

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 space-y-5" dir="rtl">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-800">خطة شيكات جديدة</h2>
        <button onClick={onCancel} className="text-gray-400 hover:text-gray-600 text-2xl">&times;</button>
      </div>

      {/* Section: Basic */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-600 border-b pb-1">بيانات أساسية</h3>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">عنوان الخطة *</label>
          <input value={form.title} onChange={e => set('title', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none"
            placeholder="مثال: دفعات مورد ABC - مارس 2025" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">اسم المستفيد *</label>
            <input value={form.payee_name} onChange={e => set('payee_name', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none"
              placeholder="اسم الشركة أو المورد" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">رقم المستند المرجعي</label>
            <input value={form.reference_doc} onChange={e => set('reference_doc', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none"
              placeholder="رقم الفاتورة / أمر الشراء" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">البنك</label>
            <input value={form.bank_name} onChange={e => set('bank_name', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none"
              placeholder="مثال: البنك الأهلي" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">رقم الحساب</label>
            <input value={form.account_number} onChange={e => set('account_number', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none" />
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">الفرع</label>
          <select value={form.branch} onChange={e => set('branch', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none">
            <option value="">— بدون فرع —</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
        </div>
      </div>

      {/* Section: Schedule */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-600 border-b pb-1">جدول السداد</h3>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">إجمالي المبلغ (ج.م) *</label>
          <input type="number" min="1" step="0.01" value={form.total_amount}
            onChange={e => set('total_amount', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none"
            placeholder="0.00" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">عدد الشيكات *</label>
            <input type="number" min="1" max="120" value={form.cheque_count}
              onChange={e => set('cheque_count', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">تاريخ الشيك الأول *</label>
            <input type="date" value={form.first_due_date}
              onChange={e => set('first_due_date', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">الفترة بين الشيكات</label>
            <input type="number" min="1" value={form.interval_value}
              onChange={e => set('interval_value', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">الوحدة</label>
            <select value={form.interval_unit} onChange={e => set('interval_unit', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none">
              <option value="months">أشهر</option>
              <option value="weeks">أسابيع</option>
              <option value="days">أيام</option>
            </select>
          </div>
        </div>

        {/* Preview button */}
        <button
          type="button"
          onClick={handlePreview}
          disabled={!canPreview || previewLoading}
          className="w-full py-2 bg-yellow-50 text-yellow-800 border border-yellow-200 rounded-lg text-sm font-medium hover:bg-yellow-100 disabled:opacity-50"
        >
          {previewLoading ? 'جارٍ الحساب...' : '📅 معاينة جدول الشيكات'}
        </button>
        <PreviewTable previewRows={previewRows} />
        {previewRows?.some(r => r.adjusted) && (
          <p className="text-xs text-yellow-700 bg-yellow-50 p-2 rounded">
            ⚠️ بعض التواريخ عُدِّلت تلقائياً لتجنب الإجازات وعطلات نهاية الأسبوع.
          </p>
        )}
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">ملاحظات</label>
        <textarea value={form.notes} onChange={e => set('notes', e.target.value)}
          rows={2}
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 focus:outline-none" />
      </div>

      <div className="flex gap-3 pt-2">
        <button
          onClick={handleSubmit}
          disabled={!form.title || !form.payee_name || !form.total_amount || !form.first_due_date || createMutation.isPending}
          className="flex-1 py-2.5 bg-indigo-600 text-white rounded-lg font-medium text-sm hover:bg-indigo-700 disabled:opacity-50"
        >
          {createMutation.isPending ? 'جارٍ الإنشاء...' : 'إنشاء الخطة'}
        </button>
        <button onClick={onCancel} className="px-4 py-2.5 bg-gray-100 text-gray-700 rounded-lg text-sm hover:bg-gray-200">
          إلغاء
        </button>
      </div>
      {createMutation.isError && (
        <p className="text-red-600 text-xs">
          {JSON.stringify(createMutation.error?.response?.data)}
        </p>
      )}
    </div>
  )
}

// ── Instalment row ────────────────────────────────────────────────────────────
function InstalmentRow({ inst, planId, planStatus }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({ cheque_number: inst.cheque_number, status: inst.status, notes: inst.notes })

  const patchMutation = useMutation({
    mutationFn: (data) => chequesApi.updateInstalment(planId, inst.id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cheque-plan', planId] })
      qc.invalidateQueries({ queryKey: ['cheques-treasury'] })
      setEditing(false)
    },
  })

  const today = new Date().toISOString().split('T')[0]
  const isPast = inst.due_date < today
  const isToday = inst.due_date === today

  const rowColor = inst.status === 'cleared'   ? 'bg-green-50'
    : inst.status === 'bounced'  ? 'bg-red-50'
    : inst.status === 'cancelled' ? 'opacity-50'
    : isPast && inst.status !== 'cleared' ? 'bg-red-50'
    : isToday ? 'bg-yellow-50'
    : ''

  return (
    <>
      <tr className={`border-t border-gray-100 hover:bg-gray-50 text-sm ${rowColor}`}>
        <td className="px-3 py-2 text-gray-500 text-center">{inst.instalment_no}</td>
        <td className="px-3 py-2">
          <span className={isPast && !['cleared','cancelled'].includes(inst.status) ? 'text-red-600 font-semibold' : ''}>
            {fmtDate(inst.due_date)}
          </span>
          {inst.adjusted && (
            <span className="mr-1 text-xs text-yellow-600" title={`الأصلي: ${fmtDate(inst.nominal_date)}`}>⚠️</span>
          )}
        </td>
        <td className="px-3 py-2 font-semibold text-indigo-700">{fmt(inst.amount)} ج.م</td>
        <td className="px-3 py-2 font-mono text-xs text-gray-600">{inst.cheque_number || '—'}</td>
        <td className="px-3 py-2">
          <StatusBadge status={inst.status} map={INST_STATUS} />
        </td>
        <td className="px-3 py-2">
          {planStatus === 'active' && !['cleared', 'cancelled'].includes(inst.status) && (
            <button
              onClick={() => setEditing(!editing)}
              className="text-xs text-indigo-600 hover:underline"
            >
              {editing ? 'إلغاء' : 'تعديل'}
            </button>
          )}
        </td>
      </tr>
      {editing && (
        <tr className="bg-indigo-50 border-t border-indigo-200">
          <td colSpan={6} className="px-4 py-3">
            <div className="flex flex-wrap gap-3 items-end" dir="rtl">
              <div>
                <label className="block text-xs text-gray-600 mb-1">رقم الشيك</label>
                <input
                  value={form.cheque_number}
                  onChange={e => setForm(f => ({ ...f, cheque_number: e.target.value }))}
                  className="px-2 py-1.5 border border-gray-200 rounded text-sm w-36"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">الحالة</label>
                <select
                  value={form.status}
                  onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
                  className="px-2 py-1.5 border border-gray-200 rounded text-sm"
                >
                  {Object.entries(INST_STATUS).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">ملاحظات</label>
                <input
                  value={form.notes}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                  className="px-2 py-1.5 border border-gray-200 rounded text-sm w-48"
                />
              </div>
              <button
                onClick={() => patchMutation.mutate(form)}
                disabled={patchMutation.isPending}
                className="px-3 py-1.5 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700 disabled:opacity-50"
              >
                {patchMutation.isPending ? '...' : 'حفظ'}
              </button>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Plan detail ───────────────────────────────────────────────────────────────
function PlanDetail({ planId, onClose }) {
  const qc = useQueryClient()

  const { data: plan, isLoading } = useQuery({
    queryKey: ['cheque-plan', planId],
    queryFn: () => chequesApi.planDetail(planId).then(r => r.data),
    enabled: !!planId,
  })

  const activateMutation = useMutation({
    mutationFn: () => chequesApi.activate(planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cheque-plans'] })
      qc.invalidateQueries({ queryKey: ['cheque-plan', planId] })
      qc.invalidateQueries({ queryKey: ['cheques-treasury'] })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => chequesApi.cancelPlan(planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cheque-plans'] })
      qc.invalidateQueries({ queryKey: ['cheque-plan', planId] })
      qc.invalidateQueries({ queryKey: ['cheques-treasury'] })
    },
  })

  if (isLoading) return <div className="p-8 text-center text-gray-400">جارٍ التحميل...</div>
  if (!plan) return null

  const progressPct = plan.cheque_count > 0
    ? Math.round((plan.cleared_count / plan.cheque_count) * 100)
    : 0

  return (
    <div className="flex flex-col h-full overflow-y-auto" dir="rtl">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white sticky top-0 z-10">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-gray-800">{plan.title}</h2>
              <StatusBadge status={plan.status} map={PLAN_STATUS} />
            </div>
            <p className="text-sm text-gray-500">{plan.payee_name}</p>
          </div>
          <div className="flex items-center gap-2">
            {plan.status === 'draft' && (
              <button
                onClick={() => activateMutation.mutate()}
                disabled={activateMutation.isPending}
                className="px-3 py-1.5 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              >
                ✅ تفعيل الخطة
              </button>
            )}
            {['draft', 'active'].includes(plan.status) && (
              <button
                onClick={() => { if (window.confirm('هل تريد إلغاء هذه الخطة؟')) cancelMutation.mutate() }}
                className="px-3 py-1.5 bg-red-50 text-red-600 border border-red-200 text-sm rounded-lg hover:bg-red-100"
              >
                إلغاء
              </button>
            )}
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl">&times;</button>
          </div>
        </div>
      </div>

      <div className="p-6 space-y-6">
        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-indigo-50 rounded-xl p-3 text-center">
            <p className="text-xl font-bold text-indigo-700">{fmt(plan.total_amount)}</p>
            <p className="text-xs text-indigo-500 mt-0.5">إجمالي ج.م</p>
          </div>
          <div className="bg-green-50 rounded-xl p-3 text-center">
            <p className="text-xl font-bold text-green-700">{fmt(plan.total_cleared)}</p>
            <p className="text-xs text-green-500 mt-0.5">تمّ صرفه</p>
          </div>
          <div className="bg-yellow-50 rounded-xl p-3 text-center">
            <p className="text-xl font-bold text-yellow-700">{plan.pending_count}</p>
            <p className="text-xs text-yellow-600 mt-0.5">شيكات متبقية</p>
          </div>
          <div className="bg-gray-50 rounded-xl p-3 text-center">
            <p className="text-xl font-bold text-gray-700">{progressPct}%</p>
            <p className="text-xs text-gray-500 mt-0.5">نسبة الإنجاز</p>
          </div>
        </div>

        {/* Progress bar */}
        <div>
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>{plan.cleared_count} صُرف</span>
            <span>{plan.cheque_count} إجمالي</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-indigo-600 h-2 rounded-full transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Meta */}
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          {plan.bank_name && (
            <>
              <span className="text-gray-500">البنك</span>
              <span className="font-medium">{plan.bank_name}</span>
            </>
          )}
          {plan.account_number && (
            <>
              <span className="text-gray-500">رقم الحساب</span>
              <span className="font-mono font-medium">{plan.account_number}</span>
            </>
          )}
          {plan.reference_doc && (
            <>
              <span className="text-gray-500">المستند</span>
              <span className="font-medium">{plan.reference_doc}</span>
            </>
          )}
          <span className="text-gray-500">التكرار</span>
          <span className="font-medium">كل {plan.interval_value} {plan.interval_label}</span>
          <span className="text-gray-500">أنشئ بواسطة</span>
          <span className="font-medium">{plan.created_by_name || '—'}</span>
        </div>

        {plan.notes && (
          <p className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3 border border-gray-200">
            {plan.notes}
          </p>
        )}

        {/* Instalments table */}
        <div>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">جدول الشيكات</h3>
          <div className="border border-gray-200 rounded-lg overflow-x-auto">
            <table className="w-full text-sm" dir="rtl">
              <thead className="bg-gray-50 text-xs text-gray-600">
                <tr>
                  <th className="px-3 py-2 text-center">#</th>
                  <th className="px-3 py-2 text-right">تاريخ الاستحقاق</th>
                  <th className="px-3 py-2 text-right">المبلغ</th>
                  <th className="px-3 py-2 text-right">رقم الشيك</th>
                  <th className="px-3 py-2 text-right">الحالة</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {(plan.instalments || []).map(inst => (
                  <InstalmentRow
                    key={inst.id}
                    inst={inst}
                    planId={plan.id}
                    planStatus={plan.status}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────
export default function ChequePlanningPage() {
  const [selectedId, setSelectedId] = useState(null)
  const [creating, setCreating] = useState(false)
  const qc = useQueryClient()

  const handleNew = () => { setSelectedId(null); setCreating(true) }
  const handleSelect = (id) => { setCreating(false); setSelectedId(id) }
  const handleCreated = (id) => {
    setCreating(false)
    setSelectedId(id)
    qc.invalidateQueries({ queryKey: ['cheque-plans'] })
  }

  return (
    <div className="flex flex-col h-screen bg-gray-50 overflow-hidden" dir="rtl">
      {/* Treasury KPIs */}
      <div className="px-6 pt-5 pb-1">
        <h1 className="text-xl font-bold text-gray-800 mb-3">📝 تخطيط الشيكات والخزينة</h1>
        <TreasuryStrip />
      </div>

      {/* Main 2-column layout */}
      <div className="flex flex-1 overflow-hidden border-t border-gray-200">
        {/* Left: plan list */}
        <div className="w-80 flex-shrink-0 h-full overflow-hidden">
          <PlanList selectedId={selectedId} onSelect={handleSelect} onNew={handleNew} />
        </div>

        {/* Right: detail or form */}
        <div className="flex-1 h-full overflow-hidden bg-white border-r border-gray-200">
          {creating && (
            <PlanForm onSave={handleCreated} onCancel={() => setCreating(false)} />
          )}
          {!creating && selectedId && (
            <PlanDetail planId={selectedId} onClose={() => setSelectedId(null)} />
          )}
          {!creating && !selectedId && (
            <div className="flex flex-col items-center justify-center h-full text-gray-400">
              <div className="text-6xl mb-4">📝</div>
              <p className="text-lg font-medium">اختر خطة لعرض تفاصيلها</p>
              <p className="text-sm mt-2">أو انقر "+ خطة جديدة" لإنشاء جدول سداد بالشيكات</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
