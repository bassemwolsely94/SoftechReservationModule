import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── Constants ──────────────────────────────────────────────────────────────────

const ROLE_LABELS = {
  admin:       'مدير النظام',
  call_center: 'كول سنتر',
  pharmacist:  'صيدلاني',
  salesperson: 'مندوب مبيعات',
  purchasing:  'مشتريات',
  delivery:    'توصيل',
  viewer:      'مشاهد فقط',
}

const ROLE_COLORS = {
  admin:       'bg-red-100 text-red-800',
  call_center: 'bg-blue-100 text-blue-800',
  pharmacist:  'bg-green-100 text-green-800',
  salesperson: 'bg-yellow-100 text-yellow-800',
  purchasing:  'bg-purple-100 text-purple-800',
  delivery:    'bg-orange-100 text-orange-800',
  viewer:      'bg-gray-100 text-gray-700',
}

const ROLES = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))

// ── Helpers ────────────────────────────────────────────────────────────────────

function RoleBadge({ role }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${ROLE_COLORS[role] || 'bg-gray-100 text-gray-700'}`}>
      {ROLE_LABELS[role] || role}
    </span>
  )
}

function StatusBadge({ isActive }) {
  return isActive
    ? <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-800">● نشط</span>
    : <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">● موقوف</span>
}

// ── User Drawer (Create / Edit) ────────────────────────────────────────────────

function UserDrawer({ user, branches, onClose, onSaved }) {
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
    phone:               user?.phone          || '',
    is_active:           user?.is_active      ?? true,
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

          {/* ERP user search (create only) */}
          {!isEdit && (
            <div>
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

          {/* Username */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">اسم المستخدم (SOFTECH) *</label>
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

          {/* Password (create only) */}
          {!isEdit && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">كلمة المرور *</label>
              <input
                type="password"
                value={form.password}
                onChange={e => set('password', e.target.value)}
                required
                minLength={6}
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
              <label className="block text-sm font-medium text-gray-700 mb-1">رقم الهاتف</label>
              <input
                type="tel" value={form.phone}
                onChange={e => set('phone', e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
              />
            </div>
          </div>

          {/* Role */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">الدور *</label>
            <select
              value={form.role}
              onChange={e => set('role', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 bg-white"
            >
              {ROLES.map(r => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>

          {/* Branch */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">الفرع الأساسي</label>
            <select
              value={form.branch}
              onChange={e => set('branch', e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 bg-white"
            >
              <option value="">— المركز الرئيسي —</option>
              {branches?.map(b => (
                <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
              ))}
            </select>
          </div>

          {/* Access flags */}
          <div className="space-y-2 bg-gray-50 rounded-lg px-4 py-3">
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
          <button
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
    if (newPw.length < 6) { setError('كلمة المرور يجب أن تكون 6 أحرف على الأقل'); return }
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
            required minLength={6}
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
            <button
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
                      <span className="font-medium text-gray-800">{ACTION_LABELS[log.action] || log.action}</span>
                      {log.changed_by_name && (
                        <span className="text-gray-400 text-xs">بواسطة {log.changed_by_name}</span>
                      )}
                    </div>
                    {log.note && <p className="text-gray-500 text-xs mt-0.5">{log.note}</p>}
                    {log.old_value && log.new_value && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        {JSON.stringify(log.old_value)} → {JSON.stringify(log.new_value)}
                      </p>
                    )}
                    {log.ip_address && <p className="text-xs text-gray-400">{log.ip_address}</p>}
                  </div>
                  <span className="text-xs text-gray-400 shrink-0">
                    {new Date(log.created_at).toLocaleString('ar-EG')}
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
  const { user: currentUser } = useAuthStore()
  const isAdmin = currentUser?.role === 'admin'

  const [search, setSearch]           = useState('')
  const [roleFilter, setRoleFilter]   = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [page, setPage]               = useState(1)

  const [drawerOpen, setDrawerOpen]   = useState(false)
  const [editUser, setEditUser]       = useState(null)
  const [resetPwUser, setResetPwUser] = useState(null)
  const [logUser, setLogUser]         = useState(null)

  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['users', { search, role: roleFilter, active: activeFilter, page }],
    queryFn: () => usersApi.list({
      search: search || undefined,
      role: roleFilter || undefined,
      is_active: activeFilter || undefined,
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
          <button
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
          <input
            type="text"
            placeholder="بحث بالاسم أو اسم المستخدم…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
          />
        </div>
        <select
          value={roleFilter}
          onChange={e => { setRoleFilter(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand-400"
        >
          <option value="">كل الأدوار</option>
          {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
        <select
          value={activeFilter}
          onChange={e => { setActiveFilter(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand-400"
        >
          <option value="">كل الحالات</option>
          <option value="true">نشط</option>
          <option value="false">موقوف</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b text-right text-xs text-gray-500 uppercase tracking-wide font-semibold">
              <th className="px-5 py-3">المستخدم</th>
              <th className="px-4 py-3">الدور</th>
              <th className="px-4 py-3">الفرع</th>
              <th className="px-4 py-3">SOFTECH</th>
              <th className="px-4 py-3">الحالة</th>
              {isAdmin && <th className="px-4 py-3 text-center">إجراءات</th>}
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
                      <div className="font-medium text-gray-900">{u.full_name}</div>
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
                <td className="px-4 py-3"><StatusBadge isActive={u.is_active} /></td>

                {/* Actions */}
                {isAdmin && (
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-center gap-1">
                      {/* Edit */}
                      <button
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
                      <button
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
                      <button
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

                      {/* Activity log */}
                      <button
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
