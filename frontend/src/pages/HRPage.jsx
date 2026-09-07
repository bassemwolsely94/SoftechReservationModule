/**
 * HRPage — Human Resources Workflow Hub
 * Tabs: Leave · Permits · Overtime · Salary Advances · Expense Claims
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { hrApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { printHRRequest } from '../components/HRPrint'
import { DateField, IdentityFields, weekdayAr } from '../components/HRForm'

// Small inline print action used across all request tables
function PrintLink({ kind, row }) {
  return (
    <button onClick={() => printHRRequest(kind, row)} title="طباعة"
      className="text-xs text-gray-500 hover:text-brand-700 hover:underline">🖨️</button>
  )
}

const STATUS_COLORS = {
  draft:     'bg-gray-100 text-gray-600',
  submitted: 'bg-amber-100 text-amber-800',
  pending:   'bg-amber-100 text-amber-800',
  approved:  'bg-green-100 text-green-800',
  rejected:  'bg-red-100 text-red-700',
  paid:      'bg-blue-100 text-blue-800',
  settled:   'bg-blue-100 text-blue-800',
  cancelled: 'bg-gray-100 text-gray-500',
}
const STATUS_LABELS = {
  draft:'مسودة', submitted:'بانتظار الموافقة', pending:'بانتظار الموافقة',
  approved:'موافق عليه', rejected:'مرفوض', paid:'مدفوع',
  settled:'تمت التسوية', cancelled:'ملغى',
}

// Statuses where the requester may still cancel their request
const CANCELLABLE = new Set(['draft', 'submitted'])

function Badge({ status }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[status] || 'bg-gray-100'}`}>
      {STATUS_LABELS[status] || status}
    </span>
  )
}

// ── Leave Requests ────────────────────────────────────────────────────────────
function LeaveTab() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ leave_type_code: '', start_date: '', end_date: '', return_to_work_date: '', days_requested: '', reason: '' })
  const [identity, setIdentity] = useState({})
  const [err, setErr] = useState(null)

  const { data: types } = useQuery({
    queryKey: ['hr', 'leave-types'],
    queryFn:  () => hrApi.leaveTypes({}).then(r => r.data),
  })
  const typeList = types?.results || types || []

  const { data, isLoading } = useQuery({
    queryKey: ['hr', 'leave-requests'],
    queryFn:  () => hrApi.leaveRequests({}).then(r => r.data),
  })
  const requests = data?.results || data || []

  const { data: balData } = useQuery({
    queryKey: ['hr', 'leave-balances'],
    queryFn:  () => hrApi.leaveBalances({}).then(r => r.data),
  })
  const balances = balData?.results || balData || []

  const submit = useMutation({
    mutationFn: () => hrApi.submitLeave({ ...form, ...identity }),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['hr', 'leave-requests'] }); setShowForm(false); setForm({ leave_type_code:'', start_date:'', end_date:'', return_to_work_date:'', days_requested:'', reason:'' }) },
    onError:    e  => setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'خطأ'),
  })

  const cancel = useMutation({
    mutationFn: id => hrApi.cancelLeave(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['hr', 'leave-requests'] }),
  })

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">طلبات الإجازة</h2>
        <button onClick={() => setShowForm(s => !s)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700">
          + طلب إجازة جديد
        </button>
      </div>

      {balances.length > 0 && (
        <div className="flex flex-wrap gap-3 mb-5">
          {balances.map(b => (
            <div key={b.id} className="bg-white border border-gray-200 rounded-xl px-4 py-3 min-w-[140px]">
              <div className="text-xs text-gray-500">{b.leave_type_name || '—'}</div>
              <div className="text-lg font-bold text-brand-700">{b.remaining_days ?? '—'}</div>
              <div className="text-[11px] text-gray-400">متبقٍ من {b.entitled_days} يوم ({b.year})</div>
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 mb-5">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">نوع الإجازة</label>
              <select value={form.leave_type_code} onChange={e => setForm(f => ({ ...f, leave_type_code: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                <option value="">اختر...</option>
                {typeList.map(t => <option key={t.id} value={t.code}>{t.name_ar || t.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">السبب</label>
              <input value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="السبب..." />
            </div>
            <DateField label="من تاريخ" value={form.start_date} onChange={v => setForm(f => ({ ...f, start_date: v }))} />
            <DateField label="إلى تاريخ" value={form.end_date} onChange={v => setForm(f => ({ ...f, end_date: v }))} />
            <div>
              <label className="block text-xs text-gray-500 mb-1">عدد الأيام</label>
              <input type="number" min="0.5" step="0.5" value={form.days_requested}
                onChange={e => setForm(f => ({ ...f, days_requested: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="مثال: 3" />
            </div>
            <DateField label="العودة للعمل يوم" value={form.return_to_work_date} onChange={v => setForm(f => ({ ...f, return_to_work_date: v }))} />
          </div>

          <IdentityFields onChange={setIdentity} />

          {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
            <button onClick={() => submit.mutate()} disabled={submit.isPending}
              className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50">
              {submit.isPending ? 'جاري...' : 'تقديم الطلب'}
            </button>
          </div>
        </div>
      )}

      {isLoading ? <div className="text-center py-10 text-gray-400">جاري التحميل...</div> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الموظف</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">كود</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">النوع</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">من</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">إلى</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الأيام</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {requests.length === 0 ? (
                <tr><td colSpan={8} className="text-center py-10 text-gray-400">لا توجد طلبات</td></tr>
              ) : requests.map(r => (
                <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{r.staff_name || '—'}</td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">{r.employee_hr_code || r.staff_code || '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{r.leave_type_name || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{r.start_date ? new Date(r.start_date).toLocaleDateString('ar-EG') : '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{r.end_date ? new Date(r.end_date).toLocaleDateString('ar-EG') : '—'}</td>
                  <td className="px-4 py-3">{r.days_requested ?? '—'}</td>
                  <td className="px-4 py-3"><Badge status={r.status} /></td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <PrintLink kind="leave" row={r} />
                    {CANCELLABLE.has(r.status) && (
                      <button onClick={() => cancel.mutate(r.id)} className="text-xs text-red-600 hover:underline mr-2">إلغاء</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Overtime Requests ─────────────────────────────────────────────────────────
function OvertimeTab() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ date: '', hours: '', reason: '' })
  const [identity, setIdentity] = useState({})
  const [err, setErr] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['hr', 'overtime'],
    queryFn:  () => hrApi.overtimeList({}).then(r => r.data),
  })
  const requests = data?.results || data || []

  const submit = useMutation({
    mutationFn: () => hrApi.submitOvertime({ ...form, ...identity }),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['hr', 'overtime'] }); setShowForm(false) },
    onError:    e  => setErr(e.response?.data?.detail || 'خطأ'),
  })

  const cancel = useMutation({
    mutationFn: id => hrApi.cancelOvertime(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['hr', 'overtime'] }),
  })

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">طلبات الإضافي</h2>
        <button onClick={() => setShowForm(s => !s)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700">
          + طلب إضافي جديد
        </button>
      </div>

      {showForm && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 mb-5">
          <div className="grid grid-cols-3 gap-4 mb-4">
            <DateField label="التاريخ" value={form.date} onChange={v => setForm(f => ({ ...f, date: v }))} />
            <div>
              <label className="block text-xs text-gray-500 mb-1">عدد الساعات</label>
              <input type="number" min="0.5" max="12" step="0.5" value={form.hours}
                onChange={e => setForm(f => ({ ...f, hours: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">السبب</label>
              <input value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
          </div>

          <IdentityFields onChange={setIdentity} />

          {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
            <button onClick={() => submit.mutate()} disabled={submit.isPending}
              className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg disabled:opacity-50">
              {submit.isPending ? 'جاري...' : 'تقديم'}
            </button>
          </div>
        </div>
      )}

      {isLoading ? <div className="text-center py-10 text-gray-400">جاري التحميل...</div> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b">
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الموظف</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">كود</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">التاريخ</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الساعات</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {requests.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-10 text-gray-400">لا توجد طلبات</td></tr>
              ) : requests.map(r => (
                <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{r.staff_name || '—'}</td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">{r.employee_hr_code || r.staff_code || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{r.date ? new Date(r.date).toLocaleDateString('ar-EG') : '—'}</td>
                  <td className="px-4 py-3">{r.hours ?? '—'}</td>
                  <td className="px-4 py-3"><Badge status={r.status} /></td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <PrintLink kind="overtime" row={r} />
                    {CANCELLABLE.has(r.status) && (
                      <button onClick={() => cancel.mutate(r.id)} className="text-xs text-red-600 hover:underline mr-2">إلغاء</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Salary Advances ───────────────────────────────────────────────────────────
function AdvancesTab() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ amount: '', repayment_date: '', reason: '' })
  const [identity, setIdentity] = useState({})
  const [err, setErr] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['hr', 'salary-advances'],
    queryFn:  () => hrApi.advanceList({}).then(r => r.data),
  })
  const advances = data?.results || data || []

  const submit = useMutation({
    mutationFn: () => hrApi.submitAdvance({ ...form, ...identity }),
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['hr', 'salary-advances'] }); setShowForm(false); setForm({ amount:'', repayment_date:'', reason:'' }) },
    onError:    e  => setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'خطأ'),
  })

  const cancel = useMutation({
    mutationFn: id => hrApi.cancelAdvance(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['hr', 'salary-advances'] }),
  })

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">سلف الرواتب</h2>
        <button onClick={() => setShowForm(s => !s)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700">
          + طلب سلفة جديدة
        </button>
      </div>

      {showForm && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 mb-5">
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">المبلغ (جنيه)</label>
              <input type="number" min="0" value={form.amount}
                onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <DateField label="تاريخ السداد" value={form.repayment_date} onChange={v => setForm(f => ({ ...f, repayment_date: v }))} />
            <div>
              <label className="block text-xs text-gray-500 mb-1">السبب</label>
              <input value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
          </div>

          <IdentityFields onChange={setIdentity} />

          {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
            <button onClick={() => submit.mutate()} disabled={submit.isPending}
              className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg disabled:opacity-50">
              {submit.isPending ? 'جاري...' : 'تقديم'}
            </button>
          </div>
        </div>
      )}

      {isLoading ? <div className="text-center py-10 text-gray-400">جاري التحميل...</div> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b">
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الموظف</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">المبلغ</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">تاريخ السداد</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">السبب</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {advances.length === 0 ? (
                <tr><td colSpan={7} className="text-center py-10 text-gray-400">لا توجد طلبات</td></tr>
              ) : advances.map(a => (
                <tr key={a.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{a.employee_name || a.staff_name || '—'}<span className="block text-[11px] text-gray-400 font-mono">{a.employee_hr_code || a.staff_code || ''}</span></td>
                  <td className="px-4 py-3 font-semibold">{a.amount ? Number(a.amount).toLocaleString('ar-EG') + ' ج' : '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{a.repayment_date ? new Date(a.repayment_date).toLocaleDateString('ar-EG') : '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{a.reason || '—'}</td>
                  <td className="px-4 py-3"><Badge status={a.status} /></td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <PrintLink kind="advance" row={a} />
                    {CANCELLABLE.has(a.status) && (
                      <button onClick={() => cancel.mutate(a.id)} className="text-xs text-red-600 hover:underline mr-2">إلغاء</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Expense Claims ────────────────────────────────────────────────────────────
// Must match apps/hr/models.py ExpenseClaim.CATEGORY_CHOICES
const EXPENSE_CATEGORIES = [
  { value: 'transport',     label: 'مواصلات' },
  { value: 'meal',          label: 'وجبات' },
  { value: 'accommodation', label: 'إقامة' },
  { value: 'stationery',    label: 'قرطاسية' },
  { value: 'equipment',     label: 'معدات' },
  { value: 'mamoriya',      label: 'مأمورية' },
  { value: 'other',         label: 'أخرى' },
]
const EMPTY_EXPENSE = {
  amount: '', category: 'transport', expense_date: '', description: '',
  trip_destination: '', trip_purpose: '', trip_start: '', trip_end: '',
  distance_km: '', transport_type: '', allowance_amount: '',
}

function ExpensesTab() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_EXPENSE)
  const [identity, setIdentity] = useState({})
  const [err, setErr] = useState(null)
  const isMamoriya = form.category === 'mamoriya'

  const { data, isLoading } = useQuery({
    queryKey: ['hr', 'expense-claims'],
    queryFn:  () => hrApi.expenseList({}).then(r => r.data),
  })
  const claims = data?.results || data || []

  const submit = useMutation({
    mutationFn: () => {
      // Base fields always sent; trip fields only for mamoriya, omitting blanks so
      // empty strings never reach the serializer's Decimal/Date fields.
      const payload = {
        category: form.category, expense_date: form.expense_date,
        amount: form.amount, description: form.description,
      }
      if (isMamoriya) {
        for (const k of ['trip_destination', 'trip_purpose', 'trip_start', 'trip_end',
                         'distance_km', 'transport_type', 'allowance_amount']) {
          if (form[k] !== '' && form[k] != null) payload[k] = form[k]
        }
      }
      return hrApi.submitExpense({ ...payload, ...identity })
    },
    onSuccess:  () => { qc.invalidateQueries({ queryKey: ['hr', 'expense-claims'] }); setShowForm(false); setForm(EMPTY_EXPENSE) },
    onError:    e  => setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'خطأ'),
  })

  const cancel = useMutation({
    mutationFn: id => hrApi.cancelExpense(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['hr', 'expense-claims'] }),
  })

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">مطالبات المصروفات</h2>
        <button onClick={() => setShowForm(s => !s)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700">
          + مطالبة جديدة
        </button>
      </div>

      {showForm && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 mb-5">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">المبلغ (جنيه)</label>
              <input type="number" min="0" value={form.amount}
                onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <DateField label="تاريخ المصروف" value={form.expense_date} onChange={v => setForm(f => ({ ...f, expense_date: v }))} />
            <div>
              <label className="block text-xs text-gray-500 mb-1">الفئة</label>
              <select value={form.category} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                {EXPENSE_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">الوصف</label>
              <input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
          </div>

          {isMamoriya && (
            <div className="grid grid-cols-2 gap-4 mb-4 border-t border-gray-200 pt-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">وجهة المأمورية <span className="text-red-500">*</span></label>
                <input value={form.trip_destination} onChange={e => setForm(f => ({ ...f, trip_destination: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="المدينة / الجهة" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">غرض المأمورية</label>
                <input value={form.trip_purpose} onChange={e => setForm(f => ({ ...f, trip_purpose: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <DateField label="تاريخ المغادرة" value={form.trip_start} onChange={v => setForm(f => ({ ...f, trip_start: v }))} />
              <DateField label="تاريخ العودة" value={form.trip_end} onChange={v => setForm(f => ({ ...f, trip_end: v }))} />
              <div>
                <label className="block text-xs text-gray-500 mb-1">المسافة (كم)</label>
                <input type="number" min="0" value={form.distance_km} onChange={e => setForm(f => ({ ...f, distance_km: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">بدل المأمورية (جنيه)</label>
                <input type="number" min="0" value={form.allowance_amount} onChange={e => setForm(f => ({ ...f, allowance_amount: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
              </div>
            </div>
          )}

          <IdentityFields onChange={setIdentity} />

          {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
            <button onClick={() => submit.mutate()} disabled={submit.isPending}
              className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg disabled:opacity-50">
              {submit.isPending ? 'جاري...' : 'تقديم'}
            </button>
          </div>
        </div>
      )}

      {isLoading ? <div className="text-center py-10 text-gray-400">جاري التحميل...</div> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b">
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الموظف</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">المبلغ</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الفئة</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الوصف</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {claims.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-10 text-gray-400">لا توجد مطالبات</td></tr>
              ) : claims.map(c => (
                <tr key={c.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{c.employee_name || c.staff_name || '—'}<span className="block text-[11px] text-gray-400 font-mono">{c.employee_hr_code || c.staff_code || ''}</span></td>
                  <td className="px-4 py-3 font-semibold">{c.amount ? Number(c.amount).toLocaleString('ar-EG') + ' ج' : '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{c.category_display || c.category || '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{c.description || '—'}</td>
                  <td className="px-4 py-3"><Badge status={c.status} /></td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <PrintLink kind="expense" row={c} />
                    {CANCELLABLE.has(c.status) && (
                      <button onClick={() => cancel.mutate(c.id)} className="text-xs text-red-600 hover:underline mr-2">إلغاء</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Permits (اذن مأمورية / اذن تعديل شيفت) ───────────────────────────────────────
const PERMIT_TYPES = [
  { value: 'mamoriya',     label: 'اذن مأمورية' },
  { value: 'shift_change', label: 'اذن تعديل شيفت' },
]
const EMPTY_PERMIT = { permit_type: 'mamoriya', date: '', time_from: '', time_to: '', destination: '', reason: '' }

function PermitsTab() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_PERMIT)
  const [identity, setIdentity] = useState({})
  const [err, setErr] = useState(null)
  const isMamoriya = form.permit_type === 'mamoriya'

  const { data, isLoading } = useQuery({
    queryKey: ['hr', 'permits'],
    queryFn:  () => hrApi.permitList({}).then(r => r.data),
  })
  const permits = data?.results || data || []

  const submit = useMutation({
    mutationFn: () => {
      const payload = {
        permit_type: form.permit_type, date: form.date,
        time_from: form.time_from, reason: form.reason,
      }
      if (form.time_to) payload.time_to = form.time_to
      if (isMamoriya && form.destination) payload.destination = form.destination
      return hrApi.submitPermit({ ...payload, ...identity })
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['hr', 'permits'] }); setShowForm(false); setForm(EMPTY_PERMIT) },
    onError:   e => setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'خطأ'),
  })

  const cancel = useMutation({
    mutationFn: id => hrApi.cancelPermit(id),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['hr', 'permits'] }),
  })

  const fmtTime = t => (t ? String(t).slice(0, 5) : '—')

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-base font-semibold text-gray-800">الأذونات (مأمورية / تعديل شيفت)</h2>
        <button onClick={() => setShowForm(s => !s)}
          className="px-4 py-2 bg-brand-600 text-white text-sm rounded-lg hover:bg-brand-700">
          + إذن جديد
        </button>
      </div>

      {showForm && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 mb-5">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">نوع الإذن</label>
              <select value={form.permit_type} onChange={e => setForm(f => ({ ...f, permit_type: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm">
                {PERMIT_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <DateField label="التاريخ" value={form.date} onChange={v => setForm(f => ({ ...f, date: v }))} />
            <div>
              <label className="block text-xs text-gray-500 mb-1">من الساعة</label>
              <input type="time" value={form.time_from} onChange={e => setForm(f => ({ ...f, time_from: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">حتى الساعة</label>
              <input type="time" value={form.time_to} onChange={e => setForm(f => ({ ...f, time_to: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
            {isMamoriya && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">جهة المأمورية <span className="text-red-500">*</span></label>
                <input value={form.destination} onChange={e => setForm(f => ({ ...f, destination: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm" placeholder="الجهة / المكان" />
              </div>
            )}
            <div className={isMamoriya ? '' : 'col-span-2'}>
              <label className="block text-xs text-gray-500 mb-1">السبب</label>
              <input value={form.reason} onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                className="w-full border rounded-lg px-3 py-2 text-sm" />
            </div>
          </div>

          <IdentityFields onChange={setIdentity} />

          {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
            <button onClick={() => submit.mutate()} disabled={submit.isPending}
              className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg disabled:opacity-50">
              {submit.isPending ? 'جاري...' : 'تقديم'}
            </button>
          </div>
        </div>
      )}

      {isLoading ? <div className="text-center py-10 text-gray-400">جاري التحميل...</div> : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b">
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الموظف</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">كود</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">النوع</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">التاريخ</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">من - حتى</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الجهة</th>
                <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {permits.length === 0 ? (
                <tr><td colSpan={8} className="text-center py-10 text-gray-400">لا توجد أذونات</td></tr>
              ) : permits.map(p => (
                <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">{p.staff_name || '—'}</td>
                  <td className="px-4 py-3 text-gray-500 font-mono text-xs">{p.employee_hr_code || p.staff_code || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{p.permit_type_display || '—'}</td>
                  <td className="px-4 py-3 text-gray-600">{p.date ? new Date(p.date).toLocaleDateString('ar-EG') : '—'}</td>
                  <td className="px-4 py-3 text-gray-600" dir="ltr">{fmtTime(p.time_from)} - {fmtTime(p.time_to)}</td>
                  <td className="px-4 py-3 text-gray-500">{p.destination || '—'}</td>
                  <td className="px-4 py-3"><Badge status={p.status} /></td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <PrintLink kind="permit" row={p} />
                    {CANCELLABLE.has(p.status) && (
                      <button onClick={() => cancel.mutate(p.id)} className="text-xs text-red-600 hover:underline mr-2">إلغاء</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main HR Page ──────────────────────────────────────────────────────────────
const TABS = [
  { key: 'leave',    label: '🏖️ الإجازات',     Component: LeaveTab    },
  { key: 'permits',  label: '📝 الأذونات',      Component: PermitsTab  },
  { key: 'overtime', label: '⏱️ الإضافي',       Component: OvertimeTab },
  { key: 'advances', label: '💵 السلف',         Component: AdvancesTab },
  { key: 'expenses', label: '🧾 المصروفات',     Component: ExpensesTab },
]

export default function HRPage() {
  const [tab, setTab] = useState('leave')
  const Active = TABS.find(t => t.key === tab)?.Component || (() => null)

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">الموارد البشرية</h1>
        <p className="text-sm text-gray-500 mt-1">إدارة الإجازات · الأذونات · الإضافي · السلف · المصروفات</p>
      </div>

      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6 flex-wrap">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      <Active />
    </div>
  )
}
