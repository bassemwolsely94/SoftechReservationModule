/**
 * pages/UsersPage.jsx
 * Works with the existing StaffProfile model.
 * No ERPUser migration required — uses softech_username/softech_user_id fields.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { usersApi, branchesApi } from '../api/client'

const ROLE_COLORS = {
  admin:       { bg: '#fef2f2', color: '#b91c1c' },
  pharmacist:  { bg: '#f5f3ff', color: '#6d28d9' },
  salesperson: { bg: '#eff6ff', color: '#1d4ed8' },
  call_center: { bg: '#f0fdf4', color: '#15803d' },
  branch:      { bg: '#fff7ed', color: '#c2410c' },
  purchasing:  { bg: '#f9fafb', color: '#374151' },
  delivery:    { bg: '#f0fdf4', color: '#15803d' },
  viewer:      { bg: '#f9fafb', color: '#6b7280' },
}

// ── Edit Modal ─────────────────────────────────────────────────────────────────
function EditModal({ staffId, roles, branches, onClose, onSaved }) {
  const qc = useQueryClient()

  const { data: staff, isLoading } = useQuery({
    queryKey: ['staff-detail', staffId],
    queryFn:  () => usersApi.getStaff(staffId).then(r => r.data),
  })

  const [form, setForm]     = useState(null)
  const [saving, setSaving] = useState(false)
  const [resetPwd, setResetPwd] = useState('')
  const [error, setError]   = useState('')
  const [tab, setTab]       = useState('role')

  if (!form && staff) {
    setForm({
      role:       staff.role,
      branch:     staff.branch || '',
      is_active:  staff.is_active !== false,
      first_name: staff.first_name || '',
      last_name:  staff.last_name  || '',
      phone:      staff.phone      || '',
    })
  }

  async function handleSave() {
    setSaving(true); setError('')
    try {
      await usersApi.updateStaff(staffId, {
        ...form,
        branch: form.branch ? Number(form.branch) : null,
      })
      qc.invalidateQueries(['staff-list'])
      onSaved()
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'object' ? Object.values(d).flat().join(' ') : 'حدث خطأ')
    } finally { setSaving(false) }
  }

  async function handleResetPwd() {
    if (resetPwd.length < 6) { setError('كلمة المرور قصيرة جداً'); return }
    try {
      await usersApi.resetPassword(staffId, resetPwd)
      setResetPwd('')
      setError('')
      alert('تم إعادة تعيين كلمة المرور بنجاح')
    } catch { setError('فشل إعادة تعيين كلمة المرور') }
  }

  if (isLoading || !form) return (
    <div style={{ position:'fixed', inset:0, zIndex:50, display:'flex', alignItems:'center', justifyContent:'center', background:'rgba(0,0,0,.4)' }}>
      <div className="card animate-fade-in" style={{ padding: 32 }}>جارٍ التحميل...</div>
    </div>
  )

  const PAGE_LABELS = {
    dashboard:'الرئيسية', reservations:'الحجوزات', demand:'الطلب الضائع',
    transfers:'التحويلات', followups:'الأدوية المزمنة', callcenter:'مركز الاتصال',
    customers:'العملاء', users:'المستخدمون', audit:'المراجعة', sync:'المزامنة',
  }

  return (
    <div className="modal-overlay" dir="rtl" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-box" style={{ maxWidth: 560 }}>
        <div className="modal-header">
          <div>
            <div style={{ fontWeight: 900, fontSize: 15, color: '#1c2833' }}>{staff?.full_name}</div>
            <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>
              @{staff?.username}
              {staff?.softech_username && ` · ERP: ${staff.softech_username}`}
              {staff?.softech_user_id && ` · ID: ${staff.softech_user_id}`}
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost" style={{ padding: 4 }}>✕</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid #f0f3f6' }}>
          {[
            { k: 'role',   label: '🎭 الدور' },
            { k: 'branch', label: '🏥 الفرع' },
            { k: 'pages',  label: '📄 الصفحات المتاحة' },
            { k: 'pwd',    label: '🔑 كلمة المرور' },
          ].map(t => (
            <button key={t.k} onClick={() => setTab(t.k)}
              style={{
                flex: 1, padding: '11px 4px', border: 'none', background: 'none',
                cursor: 'pointer', fontSize: 12.5, fontWeight: 600, fontFamily: 'Cairo,sans-serif',
                color: tab === t.k ? '#1B6B3A' : '#6b7280',
                borderBottom: tab === t.k ? '2px solid #1B6B3A' : '2px solid transparent',
                marginBottom: -1, transition: 'all .15s',
              }}>
              {t.label}
            </button>
          ))}
        </div>

        <div className="modal-body">
          {tab === 'role' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label className="label">الدور في المنصة</label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 6 }}>
                  {roles.map(r => {
                    const c = ROLE_COLORS[r.value] || { bg: '#f9fafb', color: '#6b7280' }
                    return (
                      <button key={r.value}
                        onClick={() => setForm(p => ({ ...p, role: r.value }))}
                        style={{
                          padding: '10px 12px', borderRadius: 8, cursor: 'pointer', textAlign: 'right',
                          border: form.role === r.value ? `2px solid ${c.color}` : '1px solid #e5e9ed',
                          background: form.role === r.value ? c.bg : 'white',
                          color: form.role === r.value ? c.color : '#6b7280',
                          fontWeight: 600, fontSize: 13, fontFamily: 'Cairo,sans-serif',
                          transition: 'all .15s',
                        }}>
                        {r.label}
                        <div style={{ fontSize: 11, fontWeight: 400, marginTop: 1, opacity: .7 }} dir="ltr">{r.label_en}</div>
                      </button>
                    )
                  })}
                </div>
              </div>

              <div style={{ display: 'flex', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <label className="label">الاسم الأول</label>
                  <input className="input-field" value={form.first_name}
                    onChange={e => setForm(p => ({ ...p, first_name: e.target.value }))} />
                </div>
                <div style={{ flex: 1 }}>
                  <label className="label">اسم العائلة</label>
                  <input className="input-field" value={form.last_name}
                    onChange={e => setForm(p => ({ ...p, last_name: e.target.value }))} />
                </div>
              </div>

              <div>
                <label className="label">الهاتف</label>
                <input className="input-field" value={form.phone}
                  onChange={e => setForm(p => ({ ...p, phone: e.target.value }))} dir="ltr" />
              </div>

              <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                <input type="checkbox" checked={form.is_active}
                  onChange={e => setForm(p => ({ ...p, is_active: e.target.checked }))}
                  style={{ width: 16, height: 16, accentColor: '#1B6B3A' }} />
                <span style={{ fontWeight: 600, fontSize: 13, color: '#1c2833' }}>الحساب نشط</span>
              </label>
            </div>
          )}

          {tab === 'branch' && (
            <div>
              <label className="label">الفرع الافتراضي</label>
              <select className="input-field" value={form.branch}
                onChange={e => setForm(p => ({ ...p, branch: e.target.value }))}>
                <option value="">بدون فرع محدد</option>
                {branches.map(b => (
                  <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
                ))}
              </select>
              <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 8 }}>
                الفرع الافتراضي يُستخدم لتصفية البيانات التلقائية عند دخول المستخدم.
              </p>
            </div>
          )}

          {tab === 'pages' && (
            <div>
              <p style={{ fontSize: 13, color: '#6b7280', marginBottom: 12 }}>
                الصفحات المتاحة تُحدَّد تلقائياً بناءً على الدور المختار:
                <strong style={{ color: '#1B6B3A' }}> {roles.find(r => r.value === form.role)?.label}</strong>
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {Object.entries(PAGE_LABELS).map(([key, label]) => {
                  const allowedForRole = {
                    admin:       Object.keys(PAGE_LABELS),
                    pharmacist:  ['dashboard','reservations','demand','transfers','followups','customers'],
                    salesperson: ['dashboard','reservations','demand','followups','customers'],
                    call_center: ['dashboard','reservations','demand','followups','callcenter','customers'],
                    branch:      ['dashboard','reservations','demand','transfers','followups','customers'],
                    purchasing:  ['dashboard','transfers','demand'],
                    delivery:    ['dashboard','reservations'],
                    viewer:      ['dashboard'],
                  }[form.role] || ['dashboard']
                  const allowed = allowedForRole.includes(key)
                  return (
                    <span key={key} style={{
                      padding: '4px 12px', borderRadius: 20, fontSize: 12.5, fontWeight: 600,
                      background: allowed ? '#f0fdf4' : '#f9fafb',
                      color: allowed ? '#15803d' : '#9ca3af',
                      border: `1px solid ${allowed ? '#86efac' : '#e5e7eb'}`,
                    }}>
                      {allowed ? '✓' : '—'} {label}
                    </span>
                  )
                })}
              </div>
              <p style={{ fontSize: 11.5, color: '#9ca3af', marginTop: 12 }}>
                لتغيير الصلاحيات يدوياً، تواصل مع مطور النظام.
              </p>
            </div>
          )}

          {tab === 'pwd' && (
            <div>
              <label className="label">كلمة المرور الجديدة</label>
              <input type="password" className="input-field" style={{ marginBottom: 10 }}
                placeholder="6 أحرف على الأقل"
                value={resetPwd}
                onChange={e => setResetPwd(e.target.value)} />
              <button onClick={handleResetPwd}
                disabled={resetPwd.length < 6}
                className="btn-danger btn-sm"
                style={{ opacity: resetPwd.length < 6 ? .5 : 1 }}>
                🔑 إعادة التعيين
              </button>
            </div>
          )}

          {error && (
            <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 8, background: '#fef2f2', color: '#dc2626', fontSize: 13 }}>
              {error}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="btn-secondary">إلغاء</button>
          <button onClick={handleSave} disabled={saving} className="btn-primary"
            style={{ opacity: saving ? .6 : 1 }}>
            {saving ? 'جارٍ الحفظ...' : '💾 حفظ التغييرات'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function UsersPage() {
  const qc = useQueryClient()
  const [editId, setEditId]   = useState(null)
  const [filters, setFilters] = useState({ search: '', role: '' })

  const { data: rolesData } = useQuery({
    queryKey: ['roles'],
    queryFn:  () => usersApi.staff({}).then(r => r.data.roles || []),
    staleTime: 60_000,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['staff-list', filters],
    queryFn:  () => usersApi.staff({
      search: filters.search || undefined,
      role:   filters.role   || undefined,
    }).then(r => r.data),
  })

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const staff  = data?.results || []
  const roles  = data?.roles   || rolesData || []
  const total  = data?.count   || 0

  return (
    <div className="page-pad" dir="rtl">
      {/* Header */}
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 900, color: '#1c2833', margin: 0 }}>إدارة المستخدمين</h1>
          <p style={{ fontSize: 13, color: '#9ca3af', margin: '4px 0 0' }}>
            {total} مستخدم · مزامن من SOFTECH تلقائياً عبر جدول users
          </p>
        </div>
      </div>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
        <input className="input-field" style={{ width: 240 }}
          placeholder="🔍 بحث بالاسم أو اسم المستخدم أو كود ERP..."
          value={filters.search}
          onChange={e => setFilters(p => ({ ...p, search: e.target.value }))} />
        <select className="input-field" style={{ width: 180 }}
          value={filters.role}
          onChange={e => setFilters(p => ({ ...p, role: e.target.value }))}>
          <option value="">كل الأدوار</option>
          {roles.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
        {(filters.search || filters.role) && (
          <button onClick={() => setFilters({ search: '', role: '' })} className="btn-ghost">× مسح</button>
        )}
      </div>

      {/* Info banner */}
      <div style={{ background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 10, padding: '10px 16px', marginBottom: 16, fontSize: 12.5, color: '#15803d', lineHeight: 1.6 }}>
        <strong>ملاحظة:</strong> المستخدمون يُزامَنون تلقائياً من جدول <code style={{ background: '#dcfce7', padding: '1px 6px', borderRadius: 4 }}>users</code> في SOFTECH.
        كود ERP واسم المستخدم وفرع العمل محددة من النظام. يمكنك تعديل الدور والصلاحيات وكلمة المرور من هنا.
      </div>

      {/* Table */}
      <div style={{ background: 'white', borderRadius: 12, border: '1px solid #e5e9ed', overflow: 'hidden' }}>
        {isLoading ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
            <div className="skeleton" style={{ height: 20, width: 200, margin: '0 auto 8px' }} />
            <div className="skeleton" style={{ height: 20, width: 160, margin: '0 auto' }} />
          </div>
        ) : staff.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">👥</div>
            <div className="empty-state-text">لا توجد مستخدمون</div>
            <div className="empty-state-sub">قم بتشغيل المزامنة لاستيراد مستخدمي SOFTECH</div>
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>المستخدم</th>
                <th>كود ERP</th>
                <th>الدور</th>
                <th>الفرع</th>
                <th>الحالة</th>
                <th>الصفحات المتاحة</th>
                <th style={{ width: 80 }} />
              </tr>
            </thead>
            <tbody>
              {staff.map(s => {
                const roleCfg = ROLE_COLORS[s.role] || { bg: '#f9fafb', color: '#6b7280' }
                return (
                  <tr key={s.id} onClick={() => setEditId(s.id)}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{
                          width: 34, height: 34, borderRadius: '50%', flexShrink: 0,
                          background: '#f0fdf4', color: '#1B6B3A',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontWeight: 700, fontSize: 13,
                        }}>
                          {(s.full_name || s.username || '?')[0]}
                        </div>
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 13.5, color: '#1c2833' }}>
                            {s.full_name || s.username}
                          </div>
                          <div style={{ fontSize: 11.5, color: '#9ca3af', fontFamily: 'monospace' }}>
                            @{s.username}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#6b7280' }}>
                        {s.softech_username || '—'}
                      </div>
                      {s.softech_user_id && (
                        <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#9ca3af' }}>
                          ID: {s.softech_user_id}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className="badge" style={{ background: roleCfg.bg, color: roleCfg.color }}>
                        {roles.find(r => r.value === s.role)?.label || s.role}
                      </span>
                    </td>
                    <td style={{ fontSize: 13, color: '#6b7280' }}>{s.branch_name || '—'}</td>
                    <td>
                      <span className="badge" style={{
                        background: s.is_active !== false ? '#f0fdf4' : '#fef2f2',
                        color:      s.is_active !== false ? '#15803d' : '#b91c1c',
                      }}>
                        {s.is_active !== false ? 'نشط' : 'معطل'}
                      </span>
                    </td>
                    <td>
                      <div style={{ fontSize: 11.5, color: '#6b7280', maxWidth: 180 }}>
                        {(s.allowed_pages || []).slice(0, 4).join('، ')}
                        {(s.allowed_pages || []).length > 4 && ` +${(s.allowed_pages || []).length - 4}`}
                      </div>
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      <button onClick={() => setEditId(s.id)} className="btn-secondary btn-xs">
                        تعديل
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {editId && (
        <EditModal
          staffId={editId}
          roles={roles}
          branches={branches}
          onClose={() => setEditId(null)}
          onSaved={() => {
            qc.invalidateQueries(['staff-list'])
            setEditId(null)
          }}
        />
      )}
    </div>
  )
}
