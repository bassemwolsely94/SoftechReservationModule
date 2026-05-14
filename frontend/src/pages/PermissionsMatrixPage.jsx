import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── Helpers ────────────────────────────────────────────────────────────────────

function ToggleCell({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onChange}
      className={`
        w-8 h-8 rounded-lg flex items-center justify-center text-sm transition-all
        ${disabled ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer hover:scale-110'}
        ${checked
          ? 'bg-emerald-100 text-emerald-700 border-2 border-emerald-300'
          : 'bg-gray-100 text-gray-400 border-2 border-gray-200'
        }
      `}
    >
      {checked ? '✓' : '×'}
    </button>
  )
}

// ── Role label colors ──────────────────────────────────────────────────────────

const ROLE_COLORS = {
  call_center: 'bg-blue-50 text-blue-800 border-blue-200',
  pharmacist:  'bg-green-50 text-green-800 border-green-200',
  salesperson: 'bg-yellow-50 text-yellow-800 border-yellow-200',
  purchasing:  'bg-purple-50 text-purple-800 border-purple-200',
  delivery:    'bg-orange-50 text-orange-800 border-orange-200',
  viewer:      'bg-gray-50 text-gray-600 border-gray-200',
}

// ── Unsaved change indicator ───────────────────────────────────────────────────

function DirtyBadge({ count }) {
  if (!count) return null
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
      {count} تغيير غير محفوظ
    </span>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function PermissionsMatrixPage() {
  const { user: currentUser } = useAuthStore()
  const isAdmin = currentUser?.role === 'admin'
  const qc = useQueryClient()

  // Local copy of the matrix that the user edits before saving
  const [localMatrix, setLocalMatrix] = useState({})
  const [dirtyKeys, setDirtyKeys] = useState(new Set())
  const [activeRole, setActiveRole] = useState(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['permissions-matrix'],
    queryFn: () => usersApi.getPermissions().then(r => r.data),
    staleTime: 30_000,
  })

  // Populate local state when server data arrives
  useEffect(() => {
    if (data?.matrix) {
      setLocalMatrix(JSON.parse(JSON.stringify(data.matrix)))
      setDirtyKeys(new Set())
    }
  }, [data])

  // Auto-select first non-admin role
  useEffect(() => {
    if (data?.roles?.length && !activeRole) {
      setActiveRole(data.roles[0].value)
    }
  }, [data, activeRole])

  const saveMutation = useMutation({
    mutationFn: (updates) => usersApi.savePermissions(updates),
    onSuccess: () => {
      setSaveSuccess(true)
      setDirtyKeys(new Set())
      qc.invalidateQueries({ queryKey: ['permissions-matrix'] })
      setTimeout(() => setSaveSuccess(false), 3000)
    },
  })

  const toggleCell = (role, module, action) => {
    if (!isAdmin) return
    setLocalMatrix(prev => {
      const next = { ...prev }
      if (!next[role]) next[role] = {}
      if (!next[role][module]) next[role][module] = {}
      next[role][module][action] = !next[role][module][action]
      return next
    })
    const key = `${role}::${module}::${action}`
    setDirtyKeys(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)  // toggled back to original — but we track diffs vs server
      else next.add(key)
      return next
    })
  }

  const handleSave = () => {
    if (!isAdmin || !dirtyKeys.size) return
    const updates = []
    for (const key of dirtyKeys) {
      const [role, module, action] = key.split('::')
      const is_allowed = localMatrix[role]?.[module]?.[action] ?? false
      updates.push({ role, module, action, is_allowed })
    }
    saveMutation.mutate(updates)
  }

  const handleReset = () => {
    if (data?.matrix) {
      setLocalMatrix(JSON.parse(JSON.stringify(data.matrix)))
      setDirtyKeys(new Set())
    }
  }

  // ── Grant / revoke all actions for a module × role ─────────────────────────

  const setAllActions = (role, module, value) => {
    if (!isAdmin || !data?.actions) return
    setLocalMatrix(prev => {
      const next = { ...prev }
      if (!next[role]) next[role] = {}
      if (!next[role][module]) next[role][module] = {}
      for (const { value: act } of data.actions) {
        next[role][module][act] = value
      }
      return next
    })
    setDirtyKeys(prev => {
      const next = new Set(prev)
      for (const { value: act } of data.actions) {
        next.add(`${role}::${module}::${act}`)
      }
      return next
    })
  }

  // ── Derived values ─────────────────────────────────────────────────────────

  const roles   = data?.roles   || []
  const modules = data?.modules || []
  const actions = data?.actions || []

  const currentRoleData = activeRole ? (localMatrix[activeRole] || {}) : {}

  const allGrantedForModule = (module) =>
    actions.every(a => currentRoleData[module]?.[a.value] === true)

  const noneGrantedForModule = (module) =>
    actions.every(a => !currentRoleData[module]?.[a.value])

  return (
    <div className="p-6 max-w-7xl mx-auto" dir="rtl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold font-cairo text-gray-900">مصفوفة الصلاحيات</h1>
          <p className="text-sm text-gray-500 mt-0.5">تحكم في وصول كل دور إلى كل وحدة وإجراء</p>
        </div>
        <div className="flex items-center gap-3">
          <DirtyBadge count={dirtyKeys.size} />
          {saveSuccess && (
            <span className="text-sm text-emerald-600 font-medium">✓ تم الحفظ</span>
          )}
          {isAdmin && dirtyKeys.size > 0 && (
            <>
              <button
                onClick={handleReset}
                className="px-3 py-2 text-sm border border-gray-300 rounded-xl hover:bg-gray-50"
              >
                تراجع
              </button>
              <button
                onClick={handleSave}
                disabled={saveMutation.isPending}
                className="px-4 py-2 text-sm bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-50 font-medium"
              >
                {saveMutation.isPending ? 'جارٍ الحفظ…' : `حفظ التغييرات (${dirtyKeys.size})`}
              </button>
            </>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-24 text-gray-400">جارٍ التحميل…</div>
      ) : (
        <div className="flex gap-5">
          {/* Role selector sidebar */}
          <div className="w-52 shrink-0">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3 px-1">الأدوار</p>
            <div className="space-y-1.5">
              {roles.map(role => {
                const isDirty = [...dirtyKeys].some(k => k.startsWith(role.value + '::'))
                return (
                  <button
                    key={role.value}
                    onClick={() => setActiveRole(role.value)}
                    className={`
                      w-full text-right px-3 py-2.5 rounded-xl text-sm font-medium border transition-all
                      ${activeRole === role.value
                        ? `${ROLE_COLORS[role.value] || 'bg-brand-50 text-brand-800 border-brand-200'} shadow-sm`
                        : 'bg-white text-gray-600 border-gray-100 hover:bg-gray-50'
                      }
                    `}
                  >
                    <span className="flex items-center justify-between">
                      <span>{role.label}</span>
                      {isDirty && <span className="w-2 h-2 bg-amber-400 rounded-full" />}
                    </span>
                  </button>
                )
              })}
            </div>

            {/* Admin note */}
            <div className="mt-5 p-3 bg-red-50 rounded-xl border border-red-100">
              <p className="text-xs text-red-700 font-medium">👑 Admin</p>
              <p className="text-xs text-red-600 mt-0.5">للمدير وصول كامل غير قابل للتعديل</p>
            </div>
          </div>

          {/* Matrix table */}
          <div className="flex-1 overflow-x-auto">
            {activeRole ? (
              <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
                {/* Table header */}
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b">
                      <th className="px-5 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide w-48">
                        الوحدة
                      </th>
                      {actions.map(act => (
                        <th key={act.value} className="px-3 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">
                          {act.label}
                        </th>
                      ))}
                      {isAdmin && (
                        <th className="px-3 py-3 text-center text-xs font-semibold text-gray-400">
                          الكل
                        </th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {modules.map(mod => {
                      const modData = currentRoleData[mod.value] || {}
                      const allOn  = allGrantedForModule(mod.value)
                      const allOff = noneGrantedForModule(mod.value)
                      return (
                        <tr key={mod.value} className="hover:bg-gray-50/50 transition-colors">
                          {/* Module label */}
                          <td className="px-5 py-3">
                            <div className="font-medium text-gray-800 text-sm">{mod.label}</div>
                            <div className="text-xs text-gray-400 font-mono">{mod.value}</div>
                          </td>

                          {/* Action toggles */}
                          {actions.map(act => {
                            const isOn  = !!modData[act.value]
                            const isDirty = dirtyKeys.has(`${activeRole}::${mod.value}::${act.value}`)
                            return (
                              <td key={act.value} className="px-3 py-3 text-center">
                                <div className="flex flex-col items-center gap-1">
                                  <ToggleCell
                                    checked={isOn}
                                    disabled={!isAdmin}
                                    onChange={() => toggleCell(activeRole, mod.value, act.value)}
                                  />
                                  {isDirty && (
                                    <span className="w-1.5 h-1.5 bg-amber-400 rounded-full" />
                                  )}
                                </div>
                              </td>
                            )
                          })}

                          {/* Grant/revoke all toggle */}
                          {isAdmin && (
                            <td className="px-3 py-3 text-center">
                              <button
                                onClick={() => setAllActions(activeRole, mod.value, !allOn)}
                                className={`
                                  px-2 py-1 rounded text-xs font-medium transition-colors
                                  ${allOn
                                    ? 'bg-red-50 text-red-600 hover:bg-red-100'
                                    : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                                  }
                                `}
                              >
                                {allOn ? 'سحب الكل' : 'منح الكل'}
                              </button>
                            </td>
                          )}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>

                {/* Footer summary */}
                <div className="px-5 py-3 border-t bg-gray-50 flex items-center justify-between">
                  <p className="text-xs text-gray-500">
                    الدور الحالي: <strong>{roles.find(r => r.value === activeRole)?.label}</strong>
                  </p>
                  {isAdmin && (
                    <div className="flex gap-3">
                      <button
                        onClick={() => {
                          for (const mod of modules) setAllActions(activeRole, mod.value, true)
                        }}
                        className="text-xs text-emerald-600 hover:text-emerald-700 font-medium"
                      >
                        منح جميع الصلاحيات
                      </button>
                      <span className="text-gray-300">|</span>
                      <button
                        onClick={() => {
                          for (const mod of modules) setAllActions(activeRole, mod.value, false)
                        }}
                        className="text-xs text-red-600 hover:text-red-700 font-medium"
                      >
                        سحب جميع الصلاحيات
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-center text-gray-400 py-16">اختر دوراً من القائمة</div>
            )}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="mt-5 flex items-center gap-6 text-xs text-gray-500">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-emerald-100 border-2 border-emerald-300 flex items-center justify-center text-emerald-700 font-bold">✓</div>
          <span>مسموح</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-gray-100 border-2 border-gray-200 flex items-center justify-center text-gray-400 font-bold">×</div>
          <span>ممنوع</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 bg-amber-400 rounded-full" />
          <span>تغيير غير محفوظ</span>
        </div>
        {!isAdmin && (
          <div className="text-amber-600 font-medium">
            ⚠️ عرض فقط — تحتاج دور المدير لتعديل الصلاحيات
          </div>
        )}
      </div>
    </div>
  )
}
