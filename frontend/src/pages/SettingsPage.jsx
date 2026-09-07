/**
 * pages/SettingsPage.jsx
 *
 * Comprehensive system settings dashboard.
 *
 * Tabs:
 *   ⚙️  General        — pharmacy info, currency, UI language / direction
 *   🏪  Branches       — per-branch toggles, feature flags, operational state
 *   📋  Reservations   — all reservation parameters
 *   🔀  Transfers      — transfer rules
 *   🔔  Notifications  — notification gates
 *   ⟳   Sync           — SOFTECH sync schedule & batching
 *   🎫  Vouchers       — OTP, value limits
 *   📝  Dropdowns      — configurable dropdown options
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { configApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import useLangStore  from '../store/langStore'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  DEFAULT_THEME, FONT_OPTIONS, generateScale,
  applyTheme, cacheTheme,
} from '../theme/theme'

// ── i18n helpers ──────────────────────────────────────────────────────────────
// Most labels come from the DB (Arabic), English shown as sub-labels where provided.

// ── Tab definitions ───────────────────────────────────────────────────────────
const TABS = [
  { id: 'general',       label: 'عام',               label_en: 'General',       icon: '⚙️' },
  { id: 'appearance',    label: 'المظهر',             label_en: 'Appearance',    icon: '🎨' },
  { id: 'branches',      label: 'الفروع',             label_en: 'Branches',      icon: '🏪' },
  { id: 'reservations',  label: 'الحجوزات',           label_en: 'Reservations',  icon: '📋' },
  { id: 'transfers',     label: 'التحويل',            label_en: 'Transfers',     icon: '🔀' },
  { id: 'notifications', label: 'الإشعارات',          label_en: 'Notifications', icon: '🔔' },
  { id: 'sync',          label: 'المزامنة',           label_en: 'Sync',          icon: '⟳' },
  { id: 'vouchers',      label: 'القسائم',            label_en: 'Vouchers',      icon: '🎫' },
  { id: 'dropdowns',     label: 'القوائم المنسدلة',   label_en: 'Dropdowns',     icon: '📝' },
]

const DROPDOWN_KEY_LABELS = {
  reservation_channel:  { ar: 'قنوات الحجز',           en: 'Reservation Channels' },
  reservation_priority: { ar: 'أولويات الحجز',          en: 'Reservation Priorities' },
  transfer_status:      { ar: 'حالات التحويل',          en: 'Transfer Statuses' },
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function Toast({ msg, type }) {
  if (!msg) return null
  return (
    <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl shadow-xl text-sm font-semibold
      ${type === 'error' ? 'bg-red-600 text-white' : 'bg-green-600 text-white'}`}>
      {msg}
    </div>
  )
}

// ── SectionCard ───────────────────────────────────────────────────────────────
function SectionCard({ title, icon, children, accent = 'gray' }) {
  const accents = {
    gray:   'border-gray-200',
    blue:   'border-blue-200',
    green:  'border-green-200',
    amber:  'border-amber-200',
    red:    'border-red-200',
    indigo: 'border-indigo-200',
  }
  return (
    <div className={`bg-white rounded-2xl border ${accents[accent]} overflow-hidden`}>
      {title && (
        <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2.5">
          {icon && <span className="text-lg">{icon}</span>}
          <h3 className="font-semibold text-gray-800 text-sm">{title}</h3>
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  )
}

// ── SettingRow ────────────────────────────────────────────────────────────────
function SettingRow({ setting, onSaved, isAdmin = false }) {
  const [editing, setEditing] = useState(false)
  const [draft,   setDraft]   = useState(setting.value)
  const [saving,  setSaving]  = useState(false)

  const save = async () => {
    if (draft === setting.value) { setEditing(false); return }
    setSaving(true)
    try {
      await configApi.updateSetting(setting.id, draft)
      onSaved()
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  const renderInput = () => {
    if (setting.value_type === 'boolean') {
      return (
        <select value={draft} onChange={e => setDraft(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 bg-white">
          <option value="true">✅ نعم / Yes</option>
          <option value="false">❌ لا / No</option>
        </select>
      )
    }
    if (setting.value_type === 'integer' || setting.value_type === 'decimal') {
      return (
        <input type="number" value={draft} onChange={e => setDraft(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-brand-400 text-center" />
      )
    }
    return (
      <input type="text" value={draft} onChange={e => setDraft(e.target.value)}
        className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-brand-400" />
    )
  }

  const valueDisplay = () => {
    if (setting.value_type === 'boolean')
      return setting.value === 'true' ? <span className="text-green-600">✅ نعم</span> : <span className="text-red-500">❌ لا</span>
    return <span className="font-mono text-gray-700">{setting.value || <span className="text-gray-400 italic">فارغ</span>}</span>
  }

  return (
    <div className="flex items-start justify-between py-3.5 border-b border-gray-100 last:border-0 gap-4">
      <div className="flex-1 min-w-0">
        <div className="font-medium text-gray-800 text-sm">{setting.label}</div>
        {setting.description && (
          <div className="text-xs text-gray-500 mt-0.5 leading-snug">{setting.description}</div>
        )}
        <div className="text-[10px] text-gray-400 font-mono mt-0.5 bg-gray-50 inline-block px-1.5 rounded">{setting.key}</div>
      </div>
      <div className="flex items-center gap-2 shrink-0 mt-0.5">
        {editing ? (
          <>
            {renderInput()}
            <button onClick={save} disabled={saving}
              className="px-3 py-1.5 bg-brand-600 text-white rounded-lg text-xs font-semibold hover:bg-brand-700 disabled:opacity-50">
              {saving ? '…' : 'حفظ'}
            </button>
            <button onClick={() => { setDraft(setting.value); setEditing(false) }}
              className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200">
              إلغاء
            </button>
          </>
        ) : (
          <>
            <span className="text-sm bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100 max-w-[200px] truncate">
              {valueDisplay()}
            </span>
            {isAdmin && (
              <button onClick={() => { setDraft(setting.value); setEditing(true) }}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-xs text-gray-600 hover:bg-gray-50">
                تعديل
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Language Selector (General tab) ──────────────────────────────────────────
function LanguageSelector({ isAdmin }) {
  const { lang, setLang } = useLangStore()
  const [saving, setSaving] = useState(false)

  const handleChange = async (newLang) => {
    setLang(newLang)
    // Persist to DB if we have the setting
    if (isAdmin) {
      setSaving(true)
      try {
        const res = await configApi.listSettings({ category: 'general' })
        const settings = res.data.results ?? res.data
        const uiSetting = settings.find(s => s.key === 'ui_language')
        if (uiSetting) await configApi.updateSetting(uiSetting.id, newLang)
      } catch {}
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-semibold text-gray-700">لغة الواجهة / Interface Language</span>
        {saving && <span className="text-xs text-gray-400 animate-pulse">…</span>}
      </div>
      <div className="flex gap-3">
        {[
          { val: 'ar', label: 'العربية',  flag: '🇪🇬', sub: 'Arabic · RTL' },
          { val: 'en', label: 'English',  flag: '🇬🇧', sub: 'إنجليزي · LTR' },
        ].map(opt => (
          <button key={opt.val} onClick={() => handleChange(opt.val)}
            className={`flex items-center gap-3 px-4 py-3 rounded-xl border-2 transition-all text-sm font-medium
              ${lang === opt.val
                ? 'border-brand-500 bg-brand-50 text-brand-700 shadow-sm'
                : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'}`}>
            <span className="text-xl">{opt.flag}</span>
            <div className="text-right">
              <div>{opt.label}</div>
              <div className="text-[10px] text-gray-400 font-normal">{opt.sub}</div>
            </div>
            {lang === opt.val && <span className="text-brand-500 mr-1">✓</span>}
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-400 mt-2">
        التغيير فوري — لا يحتاج إعادة تحميل الصفحة. الإعداد محفوظ في المتصفح.
      </p>
    </div>
  )
}

// ── BranchCard ────────────────────────────────────────────────────────────────
function BranchCard({ branch, isAdmin, onRefresh, showToast }) {
  const [editMode, setEditMode]   = useState(false)
  const [draft,    setDraft]      = useState({ name_ar: branch.name_ar || '', phone: branch.phone || '', address: branch.address || '', latitude: branch.latitude ?? '', longitude: branch.longitude ?? '' })
  const [saving,   setSaving]     = useState(false)

  const settings = branch.settings || {}

  const saveField = async (data) => {
    setSaving(true)
    try {
      await branchesApi.update(branch.id, data)
      onRefresh()
      showToast('تم الحفظ ✓')
    } catch (e) {
      showToast(e.response?.data?.detail || 'خطأ في الحفظ', 'error')
    } finally {
      setSaving(false)
    }
  }

  const toggleFlag = async (field, current) => {
    try {
      await branchesApi.updateSettings(branch.id, { [field]: !current })
      onRefresh()
    } catch {}
  }

  const saveProfile = async () => {
    await saveField({
      ...draft,
      latitude:  draft.latitude  === '' ? null : draft.latitude,
      longitude: draft.longitude === '' ? null : draft.longitude,
    })
    setEditMode(false)
  }

  const statusColor = branch.is_active
    ? branch.is_operational ? 'bg-green-100 text-green-700 border-green-200'
                            : 'bg-amber-100 text-amber-700 border-amber-200'
    : 'bg-red-100 text-red-500 border-red-200'
  const statusLabel = !branch.is_active ? 'مغلق' : !branch.is_operational ? 'موقوف مؤقتاً' : 'يعمل'

  const FEATURE_FLAGS = [
    { field: 'allow_reservations', label: 'الحجوزات',    label_en: 'Reservations' },
    { field: 'allow_transfers',    label: 'التحويلات',   label_en: 'Transfers' },
    { field: 'allow_vouchers',     label: 'القسائم',     label_en: 'Vouchers' },
    { field: 'allow_stockcount',   label: 'الجرد',       label_en: 'Stock Count' },
    { field: 'allow_shortage',     label: 'النواقص',     label_en: 'Shortages' },
    { field: 'notifications_enabled', label: 'الإشعارات', label_en: 'Notifications' },
  ]

  return (
    <div className={`bg-white rounded-2xl border-2 overflow-hidden transition-all
      ${!branch.is_active ? 'border-red-100 opacity-75' : 'border-gray-200 hover:border-brand-200'}`}>

      {/* Header */}
      <div className="px-4 pt-4 pb-3 flex items-start justify-between gap-2">
        <div>
          <div className="font-bold text-gray-900 text-sm">{branch.name_ar || branch.name}</div>
          <div className="text-[11px] text-gray-400 font-mono">{branch.name}</div>
          <div className="flex items-center gap-1.5 mt-1.5">
            <span className={`text-[11px] px-2 py-0.5 rounded-full border font-medium ${statusColor}`}>
              {statusLabel}
            </span>
            <span className="text-[11px] text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full font-mono">
              #{branch.softech_branch_id}
            </span>
          </div>
        </div>
        {isAdmin && (
          <button onClick={() => setEditMode(e => !e)}
            className="text-xs px-2.5 py-1 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 shrink-0">
            {editMode ? '✕ إغلاق' : '✎ تعديل'}
          </button>
        )}
      </div>

      {/* Edit profile form */}
      {editMode && (
        <div className="px-4 pb-3 border-t border-gray-100 pt-3 space-y-2.5 bg-brand-50/30">
          <div>
            <label className="text-[11px] text-gray-500 mb-1 block">الاسم بالعربية</label>
            <input value={draft.name_ar} onChange={e => setDraft(d => ({ ...d, name_ar: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white" />
          </div>
          <div>
            <label className="text-[11px] text-gray-500 mb-1 block">رقم الهاتف</label>
            <input value={draft.phone} onChange={e => setDraft(d => ({ ...d, phone: e.target.value }))}
              className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white" />
          </div>
          <div>
            <label className="text-[11px] text-gray-500 mb-1 block">العنوان</label>
            <textarea value={draft.address} onChange={e => setDraft(d => ({ ...d, address: e.target.value }))}
              rows={2}
              className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white resize-none" />
          </div>
          {/* Geolocation (for delivery pickup geofencing) */}
          <div>
            <label className="text-[11px] text-gray-500 mb-1 block">📍 إحداثيات الفرع (لتحديد نطاق الاستلام)</label>
            <div className="flex gap-2">
              <input value={draft.latitude} onChange={e => setDraft(d => ({ ...d, latitude: e.target.value }))}
                placeholder="latitude" dir="ltr"
                className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white" />
              <input value={draft.longitude} onChange={e => setDraft(d => ({ ...d, longitude: e.target.value }))}
                placeholder="longitude" dir="ltr"
                className="w-full border border-gray-300 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white" />
            </div>
            <button type="button"
              onClick={() => navigator.geolocation?.getCurrentPosition(
                p => setDraft(d => ({ ...d, latitude: p.coords.latitude.toFixed(6), longitude: p.coords.longitude.toFixed(6) })),
                () => showToast('تعذّر تحديد الموقع', 'error'), { enableHighAccuracy: true })}
              className="mt-1.5 text-[11px] text-brand-600 hover:underline">استخدم موقعي الحالي (من داخل الفرع)</button>
          </div>
          <div className="flex gap-2 pt-1">
            <button onClick={saveProfile} disabled={saving}
              className="px-3 py-1.5 bg-brand-600 text-white rounded-lg text-xs font-semibold hover:bg-brand-700 disabled:opacity-50">
              {saving ? '…' : 'حفظ'}
            </button>
            <button onClick={() => setEditMode(false)}
              className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-xs hover:bg-gray-200">
              إلغاء
            </button>
          </div>
        </div>
      )}

      {/* Info chips */}
      {!editMode && (
        <div className="px-4 pb-2 space-y-0.5 text-[11px] text-gray-500">
          {branch.phone   && <div>📞 {branch.phone}</div>}
          {branch.address && <div>📍 {branch.address}</div>}
          {branch.latitude != null && branch.longitude != null
            ? <div className="text-emerald-600 font-mono" dir="ltr">🌐 {Number(branch.latitude).toFixed(5)}, {Number(branch.longitude).toFixed(5)}</div>
            : <div className="text-amber-600">⚠️ لا توجد إحداثيات — لن يعمل التحقق الجغرافي للاستلام</div>}
        </div>
      )}

      {/* Operational toggles — admin only */}
      {isAdmin && (
        <div className="px-4 pb-3 border-t border-gray-100 pt-3 flex gap-2 flex-wrap">
          {[
            { field: 'is_active',      label: 'نشط',         label_en: 'Active',      value: branch.is_active,      danger: true },
            { field: 'is_operational', label: 'قيد التشغيل', label_en: 'Operational', value: branch.is_operational, danger: false },
          ].map(({ field, label, label_en, value, danger }) => (
            <button key={field}
              onClick={() => saveField({ [field]: !value })}
              disabled={saving}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-medium transition-all disabled:opacity-50
                ${value
                  ? danger ? 'bg-green-50 text-green-700 border-green-200 hover:bg-red-50 hover:text-red-600 hover:border-red-200'
                           : 'bg-green-50 text-green-700 border-green-200 hover:bg-amber-50 hover:text-amber-600 hover:border-amber-200'
                  : danger ? 'bg-red-50 text-red-500 border-red-200 hover:bg-green-50 hover:text-green-700 hover:border-green-200'
                           : 'bg-gray-100 text-gray-500 border-gray-200 hover:bg-green-50 hover:text-green-700 hover:border-green-200'}`}>
              <span>{value ? '●' : '○'}</span>
              <span>{label}</span>
              <span className="text-[10px] opacity-60">{label_en}</span>
            </button>
          ))}
        </div>
      )}

      {/* Feature flags */}
      <div className="px-4 pb-4 border-t border-gray-100 pt-3">
        <div className="text-[11px] text-gray-400 font-medium mb-2 uppercase tracking-wide">الميزات المتاحة</div>
        <div className="grid grid-cols-3 gap-1.5">
          {FEATURE_FLAGS.map(({ field, label }) => {
            const on = settings[field] ?? true
            return (
              <button key={field}
                onClick={() => isAdmin && toggleFlag(field, on)}
                disabled={!isAdmin}
                className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-colors
                  ${on
                    ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                    : 'bg-gray-100 text-gray-400 border border-gray-200'}
                  ${isAdmin ? 'cursor-pointer hover:opacity-80' : 'cursor-default'}`}>
                <span>{on ? '✓' : '✕'}</span>
                {label}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── DropdownEditor ────────────────────────────────────────────────────────────
function DropdownEditor({ dropdownKey, options, onRefresh, isAdmin }) {
  const [adding, setAdding] = useState(false)
  const [form,   setForm]   = useState({ label: '', label_en: '', value: '', icon: '', order: 0 })
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  const submit = async () => {
    if (!form.label || !form.value) { setError('التسمية والقيمة مطلوبتان'); return }
    setSaving(true); setError(null)
    try {
      await configApi.createDropdown({ ...form, dropdown_key: dropdownKey })
      setForm({ label: '', label_en: '', value: '', icon: '', order: 0 })
      setAdding(false)
      onRefresh()
    } catch (e) {
      setError(e.response?.data?.value?.[0] || e.response?.data?.detail || 'حدث خطأ')
    } finally { setSaving(false) }
  }

  const remove = async (opt) => {
    if (opt.is_system) return
    if (!confirm(`حذف "${opt.label}"؟`)) return
    await configApi.deleteDropdown(opt.id)
    onRefresh()
  }

  const toggle = async (opt) => {
    await configApi.updateDropdown(opt.id, { is_active: !opt.is_active })
    onRefresh()
  }

  return (
    <div>
      <div className="space-y-1.5 mb-3">
        {options.length === 0 && (
          <div className="text-sm text-gray-400 py-4 text-center">لا توجد خيارات</div>
        )}
        {options.map(opt => (
          <div key={opt.id}
            className={`flex items-center gap-3 px-3 py-2 rounded-xl border transition-opacity
              ${opt.is_active ? 'border-gray-200 bg-white' : 'border-gray-100 bg-gray-50 opacity-50'}`}>
            <span className="text-lg w-6 text-center shrink-0">{opt.icon || '•'}</span>
            <div className="flex-1 min-w-0">
              <span className="text-sm font-medium text-gray-800">{opt.label}</span>
              {opt.label_en && <span className="text-xs text-gray-400 mr-1.5">({opt.label_en})</span>}
              <span className="text-[10px] font-mono text-gray-400 mr-1.5 bg-gray-100 px-1 rounded">{opt.value}</span>
            </div>
            {opt.is_system && (
              <span className="text-[10px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full border border-blue-200 shrink-0">ثابت</span>
            )}
            {isAdmin && (
              <button onClick={() => toggle(opt)}
                className={`text-xs px-2 py-0.5 rounded-full border transition-colors shrink-0
                  ${opt.is_active ? 'bg-green-50 text-green-700 border-green-200 hover:bg-red-50 hover:text-red-600 hover:border-red-200'
                                  : 'bg-gray-100 text-gray-500 border-gray-200 hover:bg-green-50 hover:text-green-700 hover:border-green-200'}`}>
                {opt.is_active ? 'مفعّل' : 'معطّل'}
              </button>
            )}
            {isAdmin && !opt.is_system && (
              <button onClick={() => remove(opt)}
                className="text-xs text-red-400 hover:text-red-600 w-6 h-6 flex items-center justify-center rounded hover:bg-red-50 shrink-0">
                ✕
              </button>
            )}
          </div>
        ))}
      </div>

      {isAdmin && (
        adding ? (
          <div className="border border-brand-200 rounded-xl p-4 bg-brand-50/40 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-600 mb-1 block">التسمية العربية *</label>
                <input value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white"
                  placeholder="مثال: طلب عبر الهاتف" />
              </div>
              <div>
                <label className="text-xs text-gray-600 mb-1 block">English Label</label>
                <input value={form.label_en} onChange={e => setForm(f => ({ ...f, label_en: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white"
                  placeholder="Phone Order" />
              </div>
              <div>
                <label className="text-xs text-gray-600 mb-1 block">القيمة (key) *</label>
                <input value={form.value} onChange={e => setForm(f => ({ ...f, value: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white"
                  placeholder="phone_order" />
              </div>
              <div>
                <label className="text-xs text-gray-600 mb-1 block">أيقونة (emoji)</label>
                <input value={form.icon} onChange={e => setForm(f => ({ ...f, icon: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-brand-400 bg-white"
                  placeholder="📞" />
              </div>
            </div>
            {error && <div className="text-xs text-red-600 bg-red-50 px-3 py-1.5 rounded-lg border border-red-200">{error}</div>}
            <div className="flex gap-2">
              <button onClick={submit} disabled={saving}
                className="px-4 py-1.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
                {saving ? '…' : 'إضافة'}
              </button>
              <button onClick={() => { setAdding(false); setError(null) }}
                className="px-4 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-sm hover:bg-gray-200">
                إلغاء
              </button>
            </div>
          </div>
        ) : (
          <button onClick={() => setAdding(true)}
            className="w-full py-2 border-2 border-dashed border-gray-300 text-gray-400 rounded-xl text-sm hover:border-brand-400 hover:text-brand-600 transition-colors">
            + إضافة خيار جديد
          </button>
        )
      )}
    </div>
  )
}

// ── SettingsGroup — card of rows for a category ───────────────────────────────
function SettingsGroup({ title, icon, settings, onSaved, isAdmin, emptyHint }) {
  if (settings.length === 0) {
    return (
      <SectionCard title={title} icon={icon}>
        <div className="text-center py-6 text-gray-400 text-sm">
          {emptyHint || (
            <>لا توجد إعدادات. شغّل <code className="bg-gray-100 px-1.5 rounded text-xs font-mono">python manage.py seed_config</code></>
          )}
        </div>
      </SectionCard>
    )
  }
  return (
    <SectionCard title={title} icon={icon}>
      {settings.map(s => (
        <SettingRow key={s.id} setting={s} onSaved={onSaved} isAdmin={isAdmin} />
      ))}
    </SectionCard>
  )
}

// ── PharmacyProfileEditor ─────────────────────────────────────────────────────
/**
 * Inline editor for the PharmacyProfile singleton.
 * Fields: name_ar, name_en, tagline_ar, website, whatsapp_number,
 *         call_center_numbers (multi-line), extra_footer_ar.
 *
 * Used in: SettingsPage → General tab.
 */
function PharmacyProfileEditor({ isAdmin }) {
  const qc = useQueryClient()

  const { data: profile, isLoading } = useQuery({
    queryKey: ['pharmacy-profile'],
    queryFn:  () => configApi.pharmacyProfile().then(r => r.data),
    staleTime: 60_000,
  })

  const [draft,   setDraft]   = useState(null)
  const [saving,  setSaving]  = useState(false)
  const [saved,   setSaved]   = useState(false)
  const [error,   setError]   = useState(null)
  const [editing, setEditing] = useState(false)

  // Populate draft when profile loads
  useEffect(() => {
    if (profile && !draft) {
      setDraft({
        name_ar:             profile.name_ar || '',
        name_en:             profile.name_en || '',
        tagline_ar:          profile.tagline_ar || '',
        website:             profile.website || '',
        whatsapp_number:     profile.whatsapp_number || '',
        call_center_numbers: (profile.call_center_numbers || []).join('\n'),
        extra_footer_ar:     profile.extra_footer_ar || '',
      })
    }
  }, [profile])

  const save = async () => {
    setSaving(true); setError(null)
    try {
      await configApi.updatePharmacy(draft)
      await qc.invalidateQueries(['pharmacy-profile'])
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
      setEditing(false)
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ أثناء الحفظ')
    } finally {
      setSaving(false)
    }
  }

  const cancel = () => {
    if (profile) setDraft({
      name_ar:             profile.name_ar || '',
      name_en:             profile.name_en || '',
      tagline_ar:          profile.tagline_ar || '',
      website:             profile.website || '',
      whatsapp_number:     profile.whatsapp_number || '',
      call_center_numbers: (profile.call_center_numbers || []).join('\n'),
      extra_footer_ar:     profile.extra_footer_ar || '',
    })
    setEditing(false)
    setError(null)
  }

  if (isLoading || !draft) {
    return <div className="text-sm text-gray-400 animate-pulse py-4 text-center">جاري التحميل...</div>
  }

  const field = (key, label, hint, multiline = false) => (
    <div key={key}>
      <label className="text-xs font-medium text-gray-600 mb-1 block">{label}</label>
      {hint && <p className="text-[10px] text-gray-400 mb-1">{hint}</p>}
      {multiline ? (
        <textarea
          value={draft[key]}
          onChange={e => setDraft(d => ({ ...d, [key]: e.target.value }))}
          disabled={!editing}
          rows={3}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 disabled:bg-gray-50 disabled:text-gray-500 resize-none"
        />
      ) : (
        <input
          type="text"
          value={draft[key]}
          onChange={e => setDraft(d => ({ ...d, [key]: e.target.value }))}
          disabled={!editing}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400 disabled:bg-gray-50 disabled:text-gray-500"
        />
      )}
    </div>
  )

  return (
    <div>
      {/* Preview bar when not editing */}
      {!editing && (
        <div className="mb-4 flex items-center gap-3 p-3 bg-emerald-50 border border-emerald-200 rounded-xl">
          <div className="flex-1 min-w-0">
            <div className="font-bold text-emerald-800 text-sm">{draft.name_ar}</div>
            <div className="text-xs text-emerald-600 mt-0.5">
              {draft.call_center_numbers
                ? draft.call_center_numbers.split('\n').filter(Boolean).map(n => `📞 ${n}`).join('  ')
                : ''}
              {draft.website && <span className="mr-3">🌐 {draft.website}</span>}
            </div>
          </div>
          {isAdmin && (
            <button
              onClick={() => setEditing(true)}
              className="px-3 py-1.5 border border-emerald-400 text-emerald-700 rounded-lg text-xs font-medium hover:bg-emerald-100 transition-colors shrink-0"
            >
              ✎ تعديل
            </button>
          )}
          {saved && <span className="text-xs text-green-600 font-semibold shrink-0">✓ تم الحفظ</span>}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {field('name_ar',  'الاسم بالعربية',    '')}
        {field('name_en',  'الاسم بالإنجليزية', '')}
        {field('tagline_ar', 'الشعار / التعريف', 'يظهر أسفل الاسم في الإيصال')}
        {field('website',  'الموقع الإلكتروني', 'مثال: www.elrezeiky.com')}
        {field('whatsapp_number', 'رقم واتساب الرئيسي', 'بدون + (مثال: 201055000468) — يُستخدم في رمز QR')}
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        {field('call_center_numbers', 'أرقام الاتصال',
          'كل رقم في سطر منفصل — تظهر في الإيصال ورسالة واتساب العميل',
          true)}
        {field('extra_footer_ar', 'نص تذييل إضافي',
          'نص اختياري يظهر في أسفل الإيصال (مثال: "متاحون 24/7")',
          true)}
      </div>

      {error && (
        <div className="mt-3 text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {editing && (
        <div className="flex gap-2 mt-4 pt-4 border-t border-gray-100">
          <button
            onClick={save}
            disabled={saving}
            className="px-4 py-2 bg-brand-600 text-white rounded-xl text-sm font-semibold hover:bg-brand-700 disabled:opacity-50 transition-colors"
          >
            {saving ? 'جاري الحفظ...' : '💾 حفظ التغييرات'}
          </button>
          <button
            onClick={cancel}
            className="px-4 py-2 bg-gray-100 text-gray-600 rounded-xl text-sm hover:bg-gray-200 transition-colors"
          >
            إلغاء
          </button>
        </div>
      )}

      {/* Live preview of QR */}
      {draft.whatsapp_number && (
        <div className="mt-4 pt-4 border-t border-gray-100 flex items-center gap-4">
          <img
            src={`https://api.qrserver.com/v1/create-qr-code/?size=80x80&data=https%3A%2F%2Fwa.me%2F${draft.whatsapp_number}&bgcolor=ffffff&color=059669&margin=3`}
            alt="QR Preview"
            width={80}
            height={80}
            className="border border-emerald-200 rounded-lg"
          />
          <div className="text-xs text-gray-500">
            <div className="font-medium text-gray-700 mb-1">معاينة رمز QR</div>
            <div>يمكن للعميل مسح هذا الرمز لبدء محادثة واتساب</div>
            <div className="font-mono mt-1 text-gray-400" dir="ltr">wa.me/{draft.whatsapp_number}</div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── AppearanceTab — global brand theme (colors + Arabic font) ─────────────────
/**
 * Admin-editable, global (not per-user) brand theme. Changes apply live to the
 * whole app via CSS variables (src/theme/theme.js) and persist server-side
 * (SystemSetting key='theme', public read). Non-admins see a read-only view.
 */
function AppearanceTab({ isAdmin, lang, showToast }) {
  const [draft,  setDraft]  = useState(null)   // working copy
  const [saved,  setSaved]  = useState(null)   // last persisted theme
  const [saving, setSaving] = useState(false)
  const savedRef = useRef(null)

  // Load current theme
  useEffect(() => {
    let alive = true
    configApi.getTheme()
      .then(({ data }) => { if (!alive) return; const t = { ...DEFAULT_THEME, ...data }; setDraft(t); setSaved(t); savedRef.current = t })
      .catch(() => { if (alive) { setDraft({ ...DEFAULT_THEME }); setSaved({ ...DEFAULT_THEME }); savedRef.current = { ...DEFAULT_THEME } } })
    return () => { alive = false }
  }, [])

  // On unmount, if there are unsaved edits, revert the live theme to the saved one
  useEffect(() => () => { if (savedRef.current) applyTheme(savedRef.current) }, [])

  // Live-preview every draft change across the whole app
  const patch = (key, val) => {
    setDraft(d => { const next = { ...d, [key]: val }; applyTheme(next); return next })
  }

  const t   = lang === 'en'
  const dirty = draft && saved && JSON.stringify(draft) !== JSON.stringify(saved)

  const save = async () => {
    setSaving(true)
    try {
      const { data } = await configApi.updateTheme(draft)
      const next = { ...DEFAULT_THEME, ...data }
      applyTheme(next); cacheTheme(next)
      setSaved(next); savedRef.current = next; setDraft(next)
      showToast(t ? 'Theme saved ✓' : 'تم حفظ المظهر ✓')
    } catch (e) {
      showToast(e.response?.data?.detail || (t ? 'Save failed' : 'فشل الحفظ'), 'error')
    } finally { setSaving(false) }
  }

  const resetToDefault = () => { setDraft({ ...DEFAULT_THEME }); applyTheme(DEFAULT_THEME) }
  const cancel = () => { setDraft(saved); applyTheme(saved) }

  if (!draft) return <div className="text-sm text-gray-400 animate-pulse py-8 text-center">{t ? 'Loading…' : 'جاري التحميل...'}</div>

  const scale = generateScale(draft.primary, draft.secondary)

  const COLORS = [
    { key: 'primary',   label_ar: 'اللون الأساسي',  label_en: 'Primary',   hint_ar: 'الأزرار، الشريط الجانبي، الروابط', hint_en: 'Buttons, nav, links' },
    { key: 'secondary', label_ar: 'اللون الثانوي',  label_en: 'Secondary', hint_ar: 'التمييز والحدود الفاتحة',           hint_en: 'Accents & light tints' },
    { key: 'accent',    label_ar: 'لون التنبيه',    label_en: 'Accent',    hint_ar: 'الحذف والتحذيرات (أحمر الهوية)',    hint_en: 'Danger / alerts (brand red)' },
  ]

  return (
    <div className="max-w-4xl space-y-5" dir={t ? 'ltr' : 'rtl'}>
      <div>
        <h2 className="text-lg font-bold text-gray-900">{t ? 'Appearance' : 'المظهر'}</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          {t ? 'Global brand colors & font — applies to everyone. Changes preview live.'
             : 'ألوان الهوية والخط — إعداد عام لكل المستخدمين. التغييرات تظهر فوراً كمعاينة.'}
        </p>
      </div>

      {!isAdmin && (
        <div className="text-xs bg-amber-50 text-amber-700 px-3 py-2 rounded-xl border border-amber-200">
          {t ? 'View only — admin required to change the theme.' : 'عرض فقط — يتطلب صلاحية مدير لتغيير المظهر.'}
        </div>
      )}

      {/* Colors */}
      <SectionCard title={t ? 'Brand Colors' : 'ألوان الهوية'} icon="🎨" accent="indigo">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {COLORS.map(c => (
            <div key={c.key}>
              <label className="text-sm font-semibold text-gray-700 block">{t ? c.label_en : c.label_ar}</label>
              <p className="text-[11px] text-gray-400 mb-2">{t ? c.hint_en : c.hint_ar}</p>
              <div className="flex items-center gap-2">
                <input type="color" value={draft[c.key]} disabled={!isAdmin}
                  onChange={e => patch(c.key, e.target.value)}
                  className="w-11 h-11 rounded-lg border border-gray-200 bg-white cursor-pointer disabled:cursor-not-allowed p-0.5 shrink-0" />
                <input type="text" value={draft[c.key]} disabled={!isAdmin}
                  onChange={e => { let v = e.target.value; if (!v.startsWith('#')) v = '#' + v; if (/^#[0-9a-fA-F]{6}$/.test(v)) patch(c.key, v.toLowerCase()); else setDraft(d => ({ ...d, [c.key]: v })) }}
                  dir="ltr"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-400 disabled:bg-gray-50 uppercase" />
              </div>
            </div>
          ))}
        </div>

        {/* Generated scale strip */}
        <div className="mt-5">
          <div className="text-[11px] text-gray-400 mb-1.5">{t ? 'Generated palette (brand-50 → brand-900)' : 'التدرج المُولّد (brand-50 ← brand-900)'}</div>
          <div className="flex rounded-lg overflow-hidden border border-gray-100 h-8">
            {Object.entries(scale).map(([step, rgb]) => (
              <div key={step} title={`brand-${step}`} className="flex-1" style={{ background: `rgb(${rgb})` }} />
            ))}
          </div>
        </div>
      </SectionCard>

      {/* Arabic font */}
      <SectionCard title={t ? 'Arabic Font' : 'الخط العربي'} icon="🔤" accent="blue">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {FONT_OPTIONS.map(f => (
            <button key={f.id} disabled={!isAdmin} onClick={() => patch('arabicFont', f.id)}
              className={`text-right p-3 rounded-xl border-2 transition-all disabled:cursor-not-allowed
                ${draft.arabicFont === f.id ? 'border-brand-500 bg-brand-50' : 'border-gray-200 bg-white hover:border-gray-300'}`}>
              <div className="flex items-center justify-between">
                <span className="text-base font-bold text-gray-800" style={{ fontFamily: { cairo: "'Cairo'", jozoor: "'Jozoor'", tajawal: "'Tajawal'" }[f.id] }}>
                  صيدليات الرزيقي
                </span>
                {draft.arabicFont === f.id && <span className="text-brand-600 text-sm">✓</span>}
              </div>
              <div className="text-[11px] text-gray-400 mt-1">{f.label} · {f.note}</div>
            </button>
          ))}
        </div>
      </SectionCard>

      {/* Live preview */}
      <SectionCard title={t ? 'Live Preview' : 'معاينة حية'} icon="👁️">
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-primary">{t ? 'Primary action' : 'إجراء أساسي'}</button>
          <button className="btn-secondary">{t ? 'Secondary' : 'ثانوي'}</button>
          <button className="btn-danger">{t ? 'Delete' : 'حذف'}</button>
          <span className="badge bg-brand-100 text-brand-700">{t ? 'Badge' : 'شارة'}</span>
          <a className="text-brand-600 font-semibold text-sm underline" href="#">{t ? 'A link' : 'رابط'}</a>
        </div>
        <div className="mt-4 card border-brand-200">
          <div className="section-title text-brand-gradient">{t ? 'Card heading' : 'عنوان بطاقة'}</div>
          <p className="text-sm text-gray-600">{t ? 'This card, buttons, links and the sidebar all follow the primary color.' : 'هذه البطاقة والأزرار والروابط والشريط الجانبي تتبع اللون الأساسي.'}</p>
        </div>
      </SectionCard>

      {/* Actions */}
      {isAdmin && (
        <div className="flex items-center gap-2 sticky bottom-0 bg-gray-50/90 backdrop-blur py-3">
          <button onClick={save} disabled={saving || !dirty}
            className="px-5 py-2.5 bg-brand-600 text-white rounded-xl text-sm font-bold hover:bg-brand-700 disabled:opacity-40 transition-colors">
            {saving ? '…' : (t ? '💾 Save theme' : '💾 حفظ المظهر')}
          </button>
          {dirty && (
            <button onClick={cancel} className="px-4 py-2.5 bg-gray-100 text-gray-600 rounded-xl text-sm hover:bg-gray-200">
              {t ? 'Cancel' : 'إلغاء'}
            </button>
          )}
          <button onClick={resetToDefault}
            className="px-4 py-2.5 border border-gray-300 text-gray-600 rounded-xl text-sm hover:bg-gray-50 ms-auto">
            {t ? '↺ Reset to brand default' : '↺ استعادة الافتراضي'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const user       = useAuthStore(s => s.user)
  const { lang }   = useLangStore()
  const isAdmin    = user?.role === 'admin'

  const [activeTab, setActiveTab] = useState('general')
  const [settings,  setSettings]  = useState([])
  const [dropdowns, setDropdowns] = useState({})
  const [ddKeys,    setDdKeys]    = useState([])
  const [branches,  setBranches]  = useState([])
  const [loading,   setLoading]   = useState(true)
  const [toast,     setToast]     = useState(null)

  const showToast = useCallback((msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }, [])

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [sRes, dRes, kRes, bRes] = await Promise.all([
        configApi.listSettings(),
        configApi.groupedDropdowns(),
        configApi.dropdownKeys(),
        branchesApi.listAll(),
      ])
      setSettings(sRes.data.results ?? sRes.data)
      setDropdowns(dRes.data)
      setDdKeys(kRes.data)
      setBranches(bRes.data?.results ?? bRes.data ?? [])
    } catch {
      // Non-admin may get 403 on listAll — fall back to active-only
      try {
        const bRes = await branchesApi.list()
        setBranches(bRes.data?.results ?? bRes.data ?? [])
      } catch {}
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const settingsFor = (category) => settings.filter(s => s.category === category)
  const dir = lang === 'en' ? 'ltr' : 'rtl'

  // Tab label (bilingual)
  const tabLabel = (tab) => lang === 'en' ? (tab.label_en || tab.label) : tab.label

  return (
    <div className="flex flex-col h-full bg-gray-50" dir={dir}>

      <Toast msg={toast?.msg} type={toast?.type} />

      {/* ── Header ── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-2xl">⚙️</span>
          <div>
            <h1 className="text-xl font-bold text-gray-900">
              {lang === 'en' ? 'System Settings' : 'إعدادات النظام'}
            </h1>
            <p className="text-sm text-gray-500">
              {lang === 'en'
                ? 'Configure the platform, branches, and dropdown options'
                : 'تكوين منصة العمليات والفروع والقوائم المنسدلة'}
            </p>
          </div>
          {!isAdmin && (
            <span className="mr-auto text-xs bg-amber-100 text-amber-700 px-3 py-1 rounded-full border border-amber-200">
              {lang === 'en' ? 'View only — admin required to edit' : 'عرض فقط — يحتاج صلاحية مدير للتعديل'}
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">

        {/* ── Sidebar ── */}
        <nav className="w-52 bg-white border-e border-gray-200 shrink-0 py-3 px-2 space-y-0.5 overflow-y-auto">
          {TABS.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors
                ${activeTab === tab.id
                  ? 'bg-brand-600 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100'}`}>
              <span className="text-base">{tab.icon}</span>
              <span>{tabLabel(tab)}</span>
            </button>
          ))}
        </nav>

        {/* ── Content Panel ── */}
        <main className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center h-48">
              <div className="text-gray-400 animate-pulse text-sm">
                {lang === 'en' ? 'Loading…' : 'جاري التحميل...'}
              </div>
            </div>
          ) : (

            /* ─── GENERAL ───────────────────────────────────────────────── */
            activeTab === 'general' ? (
              <div className="max-w-3xl space-y-5">
                <h2 className="text-lg font-bold text-gray-900">{lang === 'en' ? 'General Settings' : 'الإعدادات العامة'}</h2>

                {/* Language & Direction */}
                <SectionCard title={lang === 'en' ? 'Interface Language & Direction' : 'لغة الواجهة والاتجاه'} icon="🌐" accent="indigo">
                  <LanguageSelector isAdmin={isAdmin} />
                </SectionCard>

                {/* Pharmacy Identity — PharmacyProfile singleton editor */}
                <SectionCard
                  title={lang === 'en' ? 'Pharmacy Chain Profile' : 'معلومات سلسلة الصيدليات'}
                  icon="🏥"
                  accent="green"
                >
                  <p className="text-xs text-gray-500 mb-4">
                    {lang === 'en'
                      ? 'These details appear on customer receipts, WhatsApp messages, and the QR code.'
                      : 'تظهر هذه البيانات في إيصالات العملاء ورسائل واتساب ورمز QR.'}
                  </p>
                  <PharmacyProfileEditor isAdmin={isAdmin} />
                </SectionCard>

                {/* Other general system settings */}
                <SettingsGroup
                  title={lang === 'en' ? 'System Settings' : 'إعدادات النظام'}
                  icon="⚙️"
                  settings={settingsFor('general').filter(s => ['pharmacy_name','pharmacy_name_en','support_phone','support_email','default_currency','timezone','date_format'].includes(s.key))}
                  onSaved={() => { loadAll(); showToast(lang === 'en' ? 'Saved ✓' : 'تم الحفظ ✓') }}
                  isAdmin={isAdmin}
                />

                {/* Display prefs */}
                <SettingsGroup
                  title={lang === 'en' ? 'Display Preferences' : 'إعدادات العرض'}
                  icon="🖥️"
                  settings={settingsFor('general').filter(s => ['items_per_page'].includes(s.key))}
                  onSaved={() => { loadAll(); showToast('تم الحفظ ✓') }}
                  isAdmin={isAdmin}
                />
              </div>

            /* ─── APPEARANCE ────────────────────────────────────────────── */
            ) : activeTab === 'appearance' ? (
              <AppearanceTab isAdmin={isAdmin} lang={lang} showToast={showToast} />

            /* ─── BRANCHES ──────────────────────────────────────────────── */
            ) : activeTab === 'branches' ? (
              <div className="max-w-5xl">
                <div className="flex items-center justify-between mb-5">
                  <div>
                    <h2 className="text-lg font-bold text-gray-900">{lang === 'en' ? 'Branch Management' : 'إدارة الفروع'}</h2>
                    <p className="text-sm text-gray-500 mt-0.5">
                      {lang === 'en'
                        ? 'Control branch status, feature flags, and contact details.'
                        : 'تحكم في حالة الفروع وميزاتها ومعلومات التواصل.'}
                    </p>
                  </div>
                  <span className="text-sm text-gray-500 bg-gray-100 px-3 py-1 rounded-full shrink-0">
                    {branches.length} {lang === 'en' ? 'branches' : 'فرع'}
                  </span>
                </div>

                {/* Legend */}
                <div className="flex gap-4 mb-4 text-xs text-gray-500 flex-wrap">
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500 inline-block"></span> {lang === 'en' ? 'Operational' : 'يعمل'}</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400 inline-block"></span> {lang === 'en' ? 'Suspended' : 'موقوف مؤقتاً'}</span>
                  <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-400 inline-block"></span> {lang === 'en' ? 'Closed' : 'مغلق'}</span>
                  {isAdmin && <span className="text-brand-600">• {lang === 'en' ? 'Click feature badges to toggle' : 'اضغط على الميزات للتفعيل/الإيقاف'}</span>}
                </div>

                {branches.length === 0 ? (
                  <div className="bg-white rounded-2xl border border-gray-200 p-12 text-center text-gray-400">
                    {lang === 'en' ? 'No branches found.' : 'لا توجد فروع.'}
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                    {branches.map(b => (
                      <BranchCard key={b.id} branch={b} isAdmin={isAdmin}
                        onRefresh={loadAll} showToast={showToast} />
                    ))}
                  </div>
                )}
              </div>

            /* ─── SETTINGS TABS (reservations / transfers / …) ─────────── */
            ) : activeTab === 'dropdowns' ? (
              <div className="space-y-6 max-w-3xl">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-bold text-gray-900">{lang === 'en' ? 'Dropdown Options' : 'القوائم المنسدلة'}</h2>
                  <span className="text-sm text-gray-500 bg-gray-100 px-3 py-1 rounded-full">{ddKeys.length} {lang === 'en' ? 'lists' : 'قائمة'}</span>
                </div>
                {ddKeys.length === 0 && (
                  <div className="bg-white rounded-2xl border border-gray-200 p-8 text-center text-gray-400 text-sm">
                    {lang === 'en' ? 'No dropdowns yet. Run ' : 'لا توجد قوائم. قم بتشغيل '}
                    <code className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">python manage.py seed_config</code>
                  </div>
                )}
                {ddKeys.map(key => {
                  const labels = DROPDOWN_KEY_LABELS[key]
                  const title  = labels ? (lang === 'en' ? labels.en : labels.ar) : key
                  return (
                    <div key={key} className="bg-white rounded-2xl border border-gray-200 p-5">
                      <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-100">
                        <h3 className="font-semibold text-gray-800">{title}</h3>
                        <span className="text-[11px] font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded">{key}</span>
                      </div>
                      <DropdownEditor dropdownKey={key} options={dropdowns[key] || []}
                        onRefresh={loadAll} isAdmin={isAdmin} />
                    </div>
                  )
                })}
              </div>

            ) : (
              /* Generic settings tab */
              <div className="max-w-3xl space-y-5">
                {(() => {
                  const tab = TABS.find(t => t.id === activeTab)
                  const cats = settingsFor(activeTab)
                  return (
                    <>
                      <h2 className="text-lg font-bold text-gray-900">
                        {lang === 'en' ? tab?.label_en : tab?.label}
                      </h2>
                      {cats.length === 0 ? (
                        <div className="bg-white rounded-2xl border border-gray-200 p-10 text-center">
                          <div className="text-4xl mb-3">📭</div>
                          <div className="text-gray-500 text-sm">
                            {lang === 'en' ? 'No settings in this category yet. Run ' : 'لا توجد إعدادات في هذه الفئة. شغّل '}
                            <code className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">python manage.py seed_config</code>
                          </div>
                        </div>
                      ) : (
                        <div className="bg-white rounded-2xl border border-gray-200 p-6">
                          <div className="flex items-center gap-2 mb-5 pb-4 border-b border-gray-100">
                            <span className="text-xl">{tab?.icon}</span>
                            <span className="text-base font-bold text-gray-900">{lang === 'en' ? tab?.label_en : tab?.label}</span>
                            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full ms-auto">
                              {cats.length} {lang === 'en' ? 'settings' : 'إعداد'}
                            </span>
                          </div>
                          {cats.map(s => (
                            <SettingRow key={s.id} setting={s}
                              onSaved={() => { loadAll(); showToast('تم الحفظ ✓') }}
                              isAdmin={isAdmin} />
                          ))}
                        </div>
                      )}
                    </>
                  )
                })()}
              </div>
            )
          )}
        </main>
      </div>
    </div>
  )
}
