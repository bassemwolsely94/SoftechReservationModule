import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi, branchesApi } from '../api/client'
import BranchSelect from '../components/BranchSelect'
import useAuthStore from '../store/authStore'
import { fa } from '../utils/flowArrow'
import useRoles, { roleOptions } from '../hooks/useRoles'
import { networkBadgeParts } from '../components/NetworkBadge'
import SortTh from '../components/SortTh'
import useServerSort from '../hooks/useServerSort'
import MultiSelectFilter from '../components/MultiSelectFilter'

// Server-side ordering (paged list): DRF `ordering` whitelist on /users/staff/.
const USER_SORT_KEYS = ['user__first_name', 'role', 'branch__name', 'softech_username', 'is_active']

// ── Constants ──────────────────────────────────────────────────────────────────


const ROLE_COLORS = {
  admin:       'bg-red-100 text-red-800',
  call_center: 'bg-blue-100 text-blue-800',
  pharmacist:  'bg-green-100 text-green-800',
  salesperson: 'bg-yellow-100 text-yellow-800',
  purchasing:  'bg-purple-100 text-purple-800',
  delivery:    'bg-orange-100 text-orange-800',
  viewer:      'bg-gray-100 text-gray-700',
  supervisor:  'bg-teal-100 text-teal-800',
  quality_manager: 'bg-pink-100 text-pink-800',
  accountant:  'bg-indigo-100 text-indigo-800',
}


// ── Helpers ────────────────────────────────────────────────────────────────────

const POS_CHANNELS = [
  { value: 'cash', label: 'نقدى' }, { value: 'delivery', label: 'توصيل' },
  { value: 'permanent', label: 'دائم' }, { value: 'contract', label: 'تعاقد' },
  { value: 'insurance', label: 'تأمين' }, { value: 'employee', label: 'موظفين' },
  { value: 'compensation', label: 'تعويضات' }, { value: 'donation', label: 'تبرعات' },
  { value: 'card_receipt', label: 'بطاقة' },
]

function RoleBadge({ role }) {
  const { roleLabel } = useRoles()
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${ROLE_COLORS[role] || 'bg-gray-100 text-gray-700'}`}>
      {roleLabel(role)}
    </span>
  )
}

function StatusBadge({ isActive }) {
  return isActive
    ? <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-800">● نشط</span>
    : <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">● موقوف</span>
}

// ── User Drawer (Create / Edit) ────────────────────────────────────────────────

const FIELD_LABELS = { alerts_only: 'تنبيهات فقط', phone_alerts_enabled: 'تنبيهات الموبايل' }

export function UserDrawer({ user, branches, onClose, onSaved }) {
  const { roles } = useRoles()
  const isEdit = Boolean(user)
  const qc = useQueryClient()

  const [form, setForm] = useState({
    username:            user?.username       || '',
    password:            '',
    first_name:          user?.first_name     || '',
    last_name:           user?.last_name      || '',
    email:               user?.email          || '',
    role:                user?.role           || 'salesperson',
    branch:              user?.branch         || '',
    access_all_branches: user?.access_all_branches || false,
    can_see_all_customers:  user?.can_see_all_customers  || false,
    can_see_customer_phone: user?.can_see_customer_phone ?? true,
    external_export:        user?.external_export        || false,
    external_softech_write: user?.external_softech_write || false,
    phone:               user?.phone          || '',
    hr_code:             user?.hr_code        || '',
    is_active:           user?.is_active      ?? true,
    alerts_only:         user?.alerts_only    || false,
    phone_alerts_enabled: user?.phone_alerts_enabled ?? true,
    allowed_pos_channels: user?.allowed_pos_channels || [],
  })

  const [erpSearch, setErpSearch] = useState('')
  const [erpUser, setErpUser] = useState(null)
  const [errors, setErrors] = useState({})

  // ERP user search (only for creation)
  const { data: erpResults } = useQuery({
    queryKey: ['erp-users', erpSearch],
    queryFn: () => usersApi.erpUsers({ search: erpSearch, no_account: '1', page_size: 10 }).then(r => r.data),
    enabled: !isEdit && erpSearch.length >= 2,
    staleTime: 30_000,
  })

  const saveMutation = useMutation({
    mutationFn: (data) => isEdit
      ? usersApi.update(user.id, data)
      : usersApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      onSaved?.()
      onClose()
    },
    onError: (err) => {
      const detail = err.response?.data
      if (typeof detail === 'object') setErrors(detail)
      else setErrors({ non_field_errors: [JSON.stringify(detail)] })
    },
  })

  const set = (key, val) => setForm(f => ({ ...f, [key]: val }))

  const handleSubmit = (e) => {
    e.preventDefault()
    setErrors({})
    const payload = { ...form }
    if (!payload.branch) delete payload.branch
    if (isEdit) {
      delete payload.username
      delete payload.password
    } else if (payload.alerts_only) {
      // alerts-only staff: WhatsApp alerts only — no login, so no password and no SOFTECH user
      delete payload.password
    } else if (!payload.password) {
      setErrors({ password: ['كلمة المرور مطلوبة'] })
      return
    }
    saveMutation.mutate(payload)
  }

  const selectErpUser = (eu) => {
    setErpUser(eu)
    setForm(f => ({
      ...f,
      username: eu.username,
      first_name: eu.full_name?.split(' ')[0] || '',
      last_name: eu.full_name?.split(' ').slice(1).join(' ') || '',
    }))
    setErpSearch('')
  }

  return (
    <div className="fixed inset-0 z-50 flex" dir="rtl">
      {/* Backdrop */}
      <div className="flex-1 bg-black/40" onClick={onClose} />

      {/* Drawer */}
      <div className="w-full max-w-md bg-white shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b bg-brand-50">
          <h2 className="text-lg font-bold font-cairo text-brand-800">
            {isEdit ? `تعديل: ${user.full_name}` : 'إضافة مستخدم جديد'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {/* Non-field errors */}
          {errors.non_field_errors && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
              {errors.non_field_errors.join(' ')}
            </div>
          )}

          {/* Field-level errors (role, branch, email, etc.) */}
          {Object.entries(errors)
            .filter(([k]) => !['non_field_errors', 'username', 'password', 'phone'].includes(k))
            .map(([k, v]) => (
              <div key={k} className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
                <span className="font-medium capitalize">{FIELD_LABELS[k] || k.replace(/_/g, ' ')}: </span>
                {Array.isArray(v) ? v.join(' ') : String(v)}
              </div>
            ))
          }

          {/* ERP user search (create only; alerts-only staff have no SOFTECH user) */}
          {!isEdit && !form.alerts_only && (
            <div data-tour="admin-users-softech-link">
              <label className="block text-sm font-medium text-gray-700 mb-1">بحث في مستخدمي SOFTECH</label>
              <input
                type="text"
                value={erpSearch}
                onChange={e => setErpSearch(e.target.value)}
                placeholder="اكتب اسم المستخدم..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
              {erpResults?.results?.length > 0 && (
                <ul className="mt-1 border border-gray-200 rounded-lg shadow-md bg-white max-h-40 overflow-y-auto">
                  {erpResults.results.map(eu => (
                    <li
                      key={eu.id}
                      onClick={() => selectErpUser(eu)}
                      className="px-3 py-2 text-sm cursor-pointer hover:bg-brand-50 flex justify-between"
                    >
                      <span className="font-medium">{eu.username}</span>
                      <span className="text-gray-500">{eu.full_name}</span>
                    </li>
                  ))}
                </ul>
              )}
              {erpUser && (
                <p className="mt-1 text-xs text-emerald-700 font-medium">
                  ✓ تم اختيار: {erpUser.username} — {erpUser.full_name}
                </p>
              )}
            </div>
          )}

          {/* Alerts-only member (WhatsApp alerts, no login) */}
          <div data-tour="admin-users-alerts-only">
            <label className="flex items-center gap-3 cursor-pointer">
              <input type="checkbox" checked={form.alerts_only}
                onChange={e => set('alerts_only', e.target.checked)}
                className="w-4 h-4 text-brand-600 rounded" />
              <span className="text-sm text-gray-700">📲 تنبيهات الموبايل فقط (بدون دخول للنظام)</span>
            </label>
            {form.alerts_only && !isEdit && (
              <p className="mt-1 text-xs text-gray-500">لا يحتاج كلمة مرور ولا مستخدم SOFTECH — رقم الموبايل مطلوب.</p>
            )}
            {isEdit && user.alerts_only && !form.alerts_only && (
                <p className="mt-1 text-xs text-amber-700">
                  إلغاء «تنبيهات فقط» لا يعيد الدخول للنظام: يجب أن يعيّن المدير كلمة مرور جديدة ثم يفعّل الحساب.
                </p>
            )}
          </div>

          {/* Username */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{form.alerts_only ? 'اسم المستخدم *' : 'اسم المستخدم (SOFTECH) *'}</label>
            <input
              type="text"
              value={form.username}
              onChange={e => set('username', e.target.value)}
              disabled={isEdit}
              required={!isEdit}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 disabled:bg-gray-50 disabled:text-gray-500"
            />
            {errors.username && <p className="mt-1 text-xs text-red-600">{errors.username.join(' ')}</p>}
          </div>

          {/* Password (create only; alerts-only staff have no login) */}
          {!isEdit && !form.alerts_only && (
            <div data-tour="admin-users-password">
              <label className="block text-sm font-medium text-gray-700 mb-1">كلمة المرور *</label>
              <input
                type="password"
                value={form.password}
                onChange={e => set('password', e.target.value)}
                required
                minLength={10}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
              {errors.password && <p className="mt-1 text-xs text-red-600">{errors.password.join(' ')}</p>}
            </div>
          )}

          {/* Name row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">الاسم الأول</label>
              <input
                type="text" value={form.first_name}
                onChange={e => set('first_name', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">الاسم الأخير</label>
              <input
                type="text" value={form.last_name}
                onChange={e => set('last_name', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
            </div>
          </div>

          {/* Email & Phone */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">البريد الإلكتروني</label>
              <input
                type="email" value={form.email}
                onChange={e => set('email', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">رقم الهاتف{form.alerts_only ? ' *' : ''}</label>
              <input
                type="tel" value={form.phone}
                onChange={e => set('phone', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
              {errors.phone && <p className="mt-1 text-xs text-red-600">{[].concat(errors.phone).join(' ')}</p>}
            </div>
            <label className="col-span-2 flex items-center gap-3 cursor-pointer" data-tour="admin-users-phone-alerts">
              <input type="checkbox" checked={form.phone_alerts_enabled}
                onChange={e => set('phone_alerts_enabled', e.target.checked)}
                className="w-4 h-4 text-brand-600 rounded" />
              <span className="text-sm text-gray-700">يستقبل تنبيهات الموبايل (واتساب)</span>
            </label>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">كود الموارد البشرية</label>
              <input
                type="text" value={form.hr_code}
                onChange={e => set('hr_code', e.target.value)}
                placeholder="كود الموظف في الموارد البشرية"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
              {errors.hr_code && <p className="text-xs text-red-600 mt-1">{errors.hr_code}</p>}
            </div>
          </div>

          {/* Role */}
          <div data-tour="admin-users-role">
            <label className="block text-sm font-medium text-gray-700 mb-1">الدور *</label>
            <select
              value={form.role}
              onChange={e => set('role', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 bg-white"
            >
              {roleOptions(roles).map(r => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>

          {/* Branch */}
          <div data-tour="admin-users-branch">
            <label className="block text-sm font-medium text-gray-700 mb-1">الفرع الأساسي</label>
            <BranchSelect
              value={form.branch}
              onChange={v => set('branch', v)}
              branches={branches ?? []}
              allLabel="— المركز الرئيسي —"
            />
          </div>

          {/* Access flags */}
          <div data-tour="admin-users-access" className="space-y-2 bg-gray-50 rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">صلاحيات الوصول</p>

            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={form.access_all_branches}
                onChange={e => set('access_all_branches', e.target.checked)}
                className="w-4 h-4 text-brand-600 rounded"
              />
              <span className="text-sm text-gray-700">وصول شامل لجميع الفروع</span>
            </label>

            {/* POS channel RBAC — which sales channels this member may operate (empty = all) */}
            <div className="pt-1">
              <span className="text-sm text-gray-700 block mb-1">قنوات البيع المسموح بها
                <span className="text-xs text-gray-400"> (فارغ = كل القنوات)</span></span>
              <div className="flex flex-wrap gap-1.5">
                {POS_CHANNELS.map(c => {
                  const on = (form.allowed_pos_channels || []).includes(c.value)
                  return (
                    <button type="button" key={c.value}
                      onClick={() => set('allowed_pos_channels', on
                        ? form.allowed_pos_channels.filter(x => x !== c.value)
                        : [...(form.allowed_pos_channels || []), c.value])}
                      className={`text-xs px-2 py-1 rounded border ${on ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-300'}`}>
                      {c.label}
                    </button>
                  )
                })}
              </div>
            </div>

            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={form.can_see_all_customers}
                onChange={e => set('can_see_all_customers', e.target.checked)}
                className="w-4 h-4 text-brand-600 rounded"
              />
              <span className="text-sm text-gray-700">يرى عملاء جميع الفروع</span>
            </label>

            <label className="flex items-center gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={form.can_see_customer_phone}
                onChange={e => set('can_see_customer_phone', e.target.checked)}
                className="w-4 h-4 text-brand-600 rounded"
              />
              <span className="text-sm text-gray-700">يرى رقم هاتف العميل</span>
            </label>

            {isEdit && form.role === 'admin' && (
              <div data-tour="admin-users-external" className="pt-1 space-y-2">
                <p className="text-xs text-gray-500">من جهاز معتمد خارج شبكة الشركة (للمدير فقط):</p>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input type="checkbox" checked={form.external_export}
                         onChange={e => set('external_export', e.target.checked)}
                         className="w-4 h-4 text-brand-600 rounded" />
                  <span className="text-sm text-gray-700">التصدير من خارج الشبكة</span>
                </label>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input type="checkbox" checked={form.external_softech_write}
                         onChange={e => set('external_softech_write', e.target.checked)}
                         className="w-4 h-4 text-brand-600 rounded" />
                  <span className="text-sm text-gray-700">الكتابة في SOFTECH من خارج الشبكة</span>
                </label>
              </div>
            )}

            {isEdit && (
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={e => set('is_active', e.target.checked)}
                  className="w-4 h-4 text-brand-600 rounded"
                />
                <span className="text-sm text-gray-700">الحساب نشط</span>
              </label>
            )}
          </div>
        </form>

        {/* Footer */}
        <div className="px-6 py-4 border-t flex gap-3 justify-end bg-gray-50">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            إلغاء
          </button>
          <button data-tour="admin-users-save"
            onClick={handleSubmit}
            disabled={saveMutation.isPending}
            className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >
            {saveMutation.isPending ? 'جارٍ الحفظ…' : isEdit ? 'حفظ التعديلات' : 'إنشاء المستخدم'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Reset Password Modal ───────────────────────────────────────────────────────

function ResetPasswordModal({ user, onClose }) {
  const [newPw, setNewPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const qc = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => usersApi.resetPassword(user.id, newPw),
    onSuccess: () => { onClose() },
    onError: (err) => setError(err.response?.data?.error || 'حدث خطأ'),
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    setError('')
    if (newPw !== confirm) { setError('كلمتا المرور غير متطابقتين'); return }
    if (newPw.length < 10) { setError('كلمة المرور يجب أن تكون 10 أحرف على الأقل'); return }
    mutation.mutate()
  }

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-96 p-6">
        <h3 className="text-lg font-bold font-cairo mb-4">إعادة تعيين كلمة المرور</h3>
        <p className="text-sm text-gray-600 mb-4">المستخدم: <strong>{user.full_name}</strong></p>
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="password"
            placeholder="كلمة المرور الجديدة"
            value={newPw}
            onChange={e => setNewPw(e.target.value)}
            required minLength={10}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
          />
          <input
            type="password"
            placeholder="تأكيد كلمة المرور"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            required
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
          />
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-2 border border-gray-300 rounded-lg text-sm">إلغاء</button>
            <button data-tour="admin-users-reset-confirm"
              type="submit"
              disabled={mutation.isPending}
              className="flex-1 py-2 bg-red-600 text-white rounded-lg text-sm hover:bg-red-700 disabled:opacity-50"
            >
              {mutation.isPending ? '…' : 'إعادة التعيين'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Activity Log Modal ─────────────────────────────────────────────────────────

const ACTION_LABELS = {
  login_success:       'دخول ناجح',
  login_failed:        'محاولة دخول فاشلة',
  password_changed:    'تغيير كلمة المرور',
  password_reset:      'إعادة تعيين كلمة المرور',
  role_changed:        'تغيير الدور',
  branch_changed:      'تغيير الفرع',
  activated:           'تفعيل الحساب',
  deactivated:         'تعطيل الحساب',
  permissions_changed: 'تغيير الصلاحيات',
  created:             'إنشاء المستخدم',
  mfa_devices_forgotten: 'إلغاء الأجهزة المحفوظة',
}

const ACTION_ICON = {
  login_success: '✅',
  login_failed:  '❌',
  password_changed: '🔑',
  password_reset:   '🔐',
  role_changed:     '🎭',
  branch_changed:   '🏥',
  activated:        '✅',
  deactivated:      '🚫',
  permissions_changed: '🔒',
  created:          '👤',
  mfa_devices_forgotten: '📵',
}

function ActivityLogModal({ user, onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ['user-activity', user.id],
    queryFn: () => usersApi.activityLog(user.id).then(r => r.data),
  })

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/50" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h3 className="text-lg font-bold font-cairo">سجل النشاط — {user.full_name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl">×</button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {isLoading ? (
            <p className="text-center text-gray-400 py-8">جارٍ التحميل…</p>
          ) : !data?.length ? (
            <p className="text-center text-gray-400 py-8">لا توجد سجلات</p>
          ) : (
            <div className="space-y-2">
              {data.map(log => (
                <div key={log.id} className="flex gap-3 items-start text-sm">
                  <span className="text-xl w-7 text-center mt-0.5">{ACTION_ICON[log.action] || '•'}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-800">{ACTION_LABELS[log.action] || log.action_label || log.action}</span>
                      {log.changed_by_name && (
                        <span className="text-gray-400 text-xs">بواسطة {log.changed_by_name}</span>
                      )}
                    </div>
                    {log.note && <p className="text-gray-500 text-xs mt-0.5">{log.note}</p>}
                    {log.old_value && log.new_value && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        {JSON.stringify(log.old_value)} {fa()} {JSON.stringify(log.new_value)}
                      </p>
                    )}
                    {log.device_name && (
                      <p className="text-xs text-gray-400">💻 {log.device_name}</p>
                    )}
                    {(log.ip_address || log.network) && (
                      <p className="text-xs text-gray-400" title={log.user_agent || undefined}>
                        {log.ip_address}
                        {log.network && (
                          <span className={`mr-2 px-1.5 py-0.5 rounded ${log.network === 'internal' ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}>
                            {networkBadgeParts({ zone: log.network, site: log.network_site ? { name: log.network_site } : null }).text}
                          </span>
                        )}
                      </p>
                    )}
                  </div>
                  <span className="text-xs text-gray-400 shrink-0">
                    {new Date(log.created_at).toLocaleString('en-US')}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function UserManagementPage() {
  const { roles } = useRoles()
  const { user: currentUser } = useAuthStore()
  const isAdmin = currentUser?.role === 'admin'

  const [search, setSearch]           = useState('')
  const [roleFilter, setRoleFilter]   = useState([])    // roles, multi-select (none = all)
  const [activeFilter, setActiveFilter] = useState('')
  const [alertsOnly, setAlertsOnly]   = useState(false)
  const [page, setPage]               = useState(1)
  const [ordering, setOrdering]       = useState('')
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: USER_SORT_KEYS })

  const [drawerOpen, setDrawerOpen]   = useState(false)
  const [editUser, setEditUser]       = useState(null)
  const [resetPwUser, setResetPwUser] = useState(null)
  const [logUser, setLogUser]         = useState(null)

  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['users', { search, role: roleFilter, active: activeFilter, alertsOnly, page, ordering }],
    queryFn: () => usersApi.list({
      search: search || undefined,
      role: roleFilter.length ? roleFilter.join(',') : undefined,
      is_active: activeFilter || undefined,
      alerts_only: alertsOnly ? 1 : undefined,
      ordering: ordering || undefined,
      page,
    }).then(r => r.data),
    keepPreviousData: true,
  })

  const { data: branches } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data),
    staleTime: 60_000,
  })

  const toggleActiveMutation = useMutation({
    mutationFn: (id) => usersApi.toggleActive(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const unlockLoginMutation = useMutation({
    mutationFn: (id) => usersApi.unlockLogin(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const forgetDevicesMutation = useMutation({
    mutationFn: (id) => usersApi.forgetDevices(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['users'] }),
  })

  const openCreate = () => { setEditUser(null); setDrawerOpen(true) }
  const openEdit   = (u)  => { setEditUser(u);  setDrawerOpen(true) }

  const users  = data?.results || []
  const total  = data?.count   || 0
  const pages  = Math.ceil(total / 30)

  return (
    <div className="p-6 max-w-7xl mx-auto" dir="rtl">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold font-cairo text-gray-900">إدارة المستخدمين</h1>
          <p className="text-sm text-gray-500 mt-0.5">{total} مستخدم إجمالاً</p>
        </div>
        {isAdmin && (
          <button data-tour="admin-users-add"
            onClick={openCreate}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 text-white rounded-xl text-sm font-medium hover:bg-brand-700 shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            إضافة مستخدم
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 mb-5 flex flex-wrap gap-3 items-center">
        <div className="flex-1 min-w-48">
          <input data-tour="admin-users-search"
            type="text"
            placeholder="بحث بالاسم أو اسم المستخدم…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
          />
        </div>
        <MultiSelectFilter dataTour="admin-users-role-filter" className="w-[180px]" menuClassName="min-w-[220px]"
          showCode={false} allLabel="كل الأدوار" options={roleOptions(roles).map(r => ({ code: r.value, name: r.label }))} selected={roleFilter}
          onChange={v => { setRoleFilter(v); setPage(1) }} />
        <select data-tour="admin-users-status-filter"
          value={activeFilter}
          onChange={e => { setActiveFilter(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand-400"
        >
          <option value="">كل الحالات</option>
          <option value="true">نشط</option>
          <option value="false">موقوف</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer" data-tour="admin-users-alerts-filter">
          <input type="checkbox" checked={alertsOnly}
            onChange={e => { setAlertsOnly(e.target.checked); setPage(1) }} />
          📲 تنبيهات فقط
        </label>
      </div>

      {/* Table */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden" data-tour="admin-users-table">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b text-right text-xs text-gray-500 uppercase tracking-wide font-semibold">
              <SortTh {...headerProps('user__first_name')} className="px-5 py-3">المستخدم</SortTh>
              <SortTh {...headerProps('role')} className="px-4 py-3">الدور</SortTh>
              <SortTh {...headerProps('branch__name')} className="px-4 py-3">الفرع</SortTh>
              <SortTh {...headerProps('softech_username')} className="px-4 py-3">SOFTECH</SortTh>
              <SortTh {...headerProps('is_active')} className="px-4 py-3">الحالة</SortTh>
              {isAdmin && <th className="px-4 py-3 text-center" data-tour="admin-users-actions">إجراءات</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? (
              <tr>
                <td colSpan={isAdmin ? 6 : 5} className="text-center py-12 text-gray-400">
                  جارٍ التحميل…
                </td>
              </tr>
            ) : !users.length ? (
              <tr>
                <td colSpan={isAdmin ? 6 : 5} className="text-center py-12 text-gray-400">
                  لا يوجد مستخدمون
                </td>
              </tr>
            ) : users.map(u => (
              <tr key={u.id} className="hover:bg-gray-50 transition-colors">
                {/* User info */}
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center font-bold text-sm shrink-0">
                      {u.full_name?.[0] || u.username?.[0] || '؟'}
                    </div>
                    <div>
                      <div className="font-medium text-gray-900">
                        {u.full_name}
                        {u.alerts_only && <span className="ms-1.5 text-[11px] font-normal text-sky-700 bg-sky-50 px-1.5 py-0.5 rounded">📲 تنبيهات فقط</span>}
                      </div>
                      <div className="text-gray-400 text-xs">{u.username}</div>
                    </div>
                  </div>
                </td>

                {/* Role */}
                <td className="px-4 py-3"><RoleBadge role={u.role} /></td>

                {/* Branch */}
                <td className="px-4 py-3 text-gray-600">
                  {u.branch_name || <span className="text-gray-300">—</span>}
                  {u.access_all_branches && (
                    <span className="mr-1 text-xs text-blue-600">• شامل</span>
                  )}
                </td>

                {/* SOFTECH */}
                <td className="px-4 py-3 text-gray-500 font-mono text-xs">{u.softech_username || '—'}</td>

                {/* Status */}
                <td className="px-4 py-3">
                  <StatusBadge isActive={u.is_active} />
                  {u.login_locked_until && (
                    <div className="mt-1 flex items-center gap-1.5">
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800"
                        title={`حتى ${new Date(u.login_locked_until).toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' })}`}>
                        🔒 دخول موقوف مؤقتاً
                      </span>
                      {isAdmin && (
                        <button data-tour="admin-users-unlock-login"
                          onClick={() => unlockLoginMutation.mutate(u.id)}
                          disabled={unlockLoginMutation.isPending}
                          className="text-xs font-medium text-brand-600 hover:underline disabled:opacity-50">
                          رفع الإيقاف
                        </button>
                      )}
                    </div>
                  )}
                </td>

                {/* Actions */}
                {isAdmin && (
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-center gap-1">
                      {/* Edit */}
                      <button data-tour="admin-users-edit"
                        onClick={() => openEdit(u)}
                        title="تعديل"
                        className="p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded-lg transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>

                      {/* Reset password */}
                      <button data-tour="admin-users-reset-password"
                        onClick={() => setResetPwUser(u)}
                        title="إعادة تعيين كلمة المرور"
                        className="p-1.5 text-gray-400 hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                        </svg>
                      </button>

                      {/* Toggle active */}
                      <button data-tour="admin-users-toggle-active"
                        onClick={() => toggleActiveMutation.mutate(u.id)}
                        title={u.is_active ? 'تعطيل الحساب' : 'تفعيل الحساب'}
                        className={`p-1.5 rounded-lg transition-colors ${u.is_active
                          ? 'text-gray-400 hover:text-red-600 hover:bg-red-50'
                          : 'text-gray-400 hover:text-emerald-600 hover:bg-emerald-50'
                        }`}
                      >
                        {u.is_active
                          ? <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                            </svg>
                          : <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                            </svg>
                        }
                      </button>

                      {/* Forget saved devices (2FA "remember this device") */}
                      <button data-tour="admin-users-forget-devices"
                        onClick={() => forgetDevicesMutation.mutate(u.id)}
                        disabled={forgetDevicesMutation.isPending}
                        title="إلغاء الأجهزة المحفوظة (يطلب رمز التحقق عند الدخول التالي)"
                        className="p-1.5 text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors disabled:opacity-50"
                      >
                        {forgetDevicesMutation.isSuccess && forgetDevicesMutation.variables === u.id ? '✓' : '📵'}
                      </button>

                      {/* Activity log */}
                      <button data-tour="admin-users-activity-log"
                        onClick={() => setLogUser(u)}
                        title="سجل النشاط"
                        className="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination */}
        {pages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 border-t bg-gray-50">
            <p className="text-xs text-gray-500">
              الصفحة {page} من {pages} ({total} نتيجة)
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1 text-xs border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-40"
              >
                السابق
              </button>
              <button
                onClick={() => setPage(p => Math.min(pages, p + 1))}
                disabled={page === pages}
                className="px-3 py-1 text-xs border border-gray-300 rounded-lg hover:bg-gray-100 disabled:opacity-40"
              >
                التالي
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      {drawerOpen && (
        <UserDrawer
          user={editUser}
          branches={branches?.results || branches || []}
          onClose={() => { setDrawerOpen(false); setEditUser(null) }}
          onSaved={() => qc.invalidateQueries({ queryKey: ['users'] })}
        />
      )}

      {resetPwUser && (
        <ResetPasswordModal
          user={resetPwUser}
          onClose={() => setResetPwUser(null)}
        />
      )}

      {logUser && (
        <ActivityLogModal
          user={logUser}
          onClose={() => setLogUser(null)}
        />
      )}
    </div>
  )
}
