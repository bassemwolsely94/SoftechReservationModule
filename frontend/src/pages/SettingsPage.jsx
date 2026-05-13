import { useState, useEffect, useCallback } from 'react'
import { configApi } from '../api/client'

// ── constants ─────────────────────────────────────────────────────────────────

const DROPDOWN_KEY_LABELS = {
  reservation_channel:  'قنوات الحجز',
  reservation_priority: 'أولويات الحجز',
  transfer_status:      'حالات التحويل (عرض)',
}

const TABS = [
  { id: 'general',       label: 'عام',               icon: '⚙️' },
  { id: 'reservations',  label: 'الحجوزات',          icon: '📋' },
  { id: 'transfers',     label: 'التحويل',           icon: '🔀' },
  { id: 'notifications', label: 'الإشعارات',         icon: '🔔' },
  { id: 'sync',          label: 'المزامنة',          icon: '⟳' },
  { id: 'vouchers',      label: 'القسائم',           icon: '🎫' },
  { id: 'dropdowns',     label: 'القوائم المنسدلة',  icon: '📝' },
]

// ── SettingRow ────────────────────────────────────────────────────────────────

function SettingRow({ setting, onSaved }) {
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
        <select
          value={draft}
          onChange={e => setDraft(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
        >
          <option value="true">نعم</option>
          <option value="false">لا</option>
        </select>
      )
    }
    if (setting.value_type === 'integer' || setting.value_type === 'decimal') {
      return (
        <input type="number" value={draft}
          onChange={e => setDraft(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-32 focus:outline-none focus:ring-2 focus:ring-brand-400"
        />
      )
    }
    return (
      <input type="text" value={draft}
        onChange={e => setDraft(e.target.value)}
        className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-brand-400"
      />
    )
  }

  return (
    <div className="flex items-center justify-between py-3.5 border-b border-gray-100 last:border-0 gap-4">
      <div className="flex-1 min-w-0">
        <div className="font-medium text-gray-800 text-sm">{setting.label}</div>
        {setting.description && (
          <div className="text-xs text-gray-500 mt-0.5">{setting.description}</div>
        )}
        <div className="text-[11px] text-gray-400 font-mono mt-0.5">{setting.key}</div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {editing ? (
          <>
            {renderInput()}
            <button onClick={save} disabled={saving}
              className="px-3 py-1.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
              {saving ? '...' : 'حفظ'}
            </button>
            <button onClick={() => { setDraft(setting.value); setEditing(false) }}
              className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded-lg text-sm hover:bg-gray-200">
              إلغاء
            </button>
          </>
        ) : (
          <>
            <span className="text-sm font-mono bg-gray-100 px-3 py-1.5 rounded-lg text-gray-700 max-w-xs truncate">
              {setting.value_type === 'boolean'
                ? (setting.value === 'true' ? '✅ نعم' : '❌ لا')
                : (setting.value || '—')}
            </span>
            <button onClick={() => { setDraft(setting.value); setEditing(true) }}
              className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
              تعديل
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ── DropdownEditor ────────────────────────────────────────────────────────────

function DropdownEditor({ dropdownKey, options, onRefresh }) {
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
    } finally {
      setSaving(false)
    }
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
              <span className="text-[11px] font-mono text-gray-400 mr-1.5 bg-gray-100 px-1 rounded">{opt.value}</span>
            </div>
            {opt.is_system && (
              <span className="text-[10px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full border border-blue-200">
                ثابت
              </span>
            )}
            <button onClick={() => toggle(opt)}
              className={`text-xs px-2 py-0.5 rounded-full border transition-colors
                ${opt.is_active ? 'bg-green-50 text-green-700 border-green-200' : 'bg-gray-100 text-gray-500 border-gray-200'}`}>
              {opt.is_active ? 'مفعّل' : 'معطّل'}
            </button>
            {!opt.is_system && (
              <button onClick={() => remove(opt)}
                className="text-xs text-red-400 hover:text-red-600 w-6 h-6 flex items-center justify-center rounded hover:bg-red-50">
                ✕
              </button>
            )}
          </div>
        ))}
      </div>

      {adding ? (
        <div className="border border-brand-200 rounded-xl p-4 bg-brand-50 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-600 mb-1 block">التسمية العربية *</label>
              <input value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                placeholder="مثال: طلب عبر الهاتف" />
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">التسمية الإنجليزية</label>
              <input value={form.label_en} onChange={e => setForm(f => ({ ...f, label_en: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                placeholder="Phone Order" />
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">القيمة (مفتاح) *</label>
              <input value={form.value} onChange={e => setForm(f => ({ ...f, value: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-400"
                placeholder="phone_order" />
            </div>
            <div>
              <label className="text-xs text-gray-600 mb-1 block">أيقونة (emoji)</label>
              <input value={form.icon} onChange={e => setForm(f => ({ ...f, icon: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-400"
                placeholder="📞" />
            </div>
          </div>
          {error && (
            <div className="text-xs text-red-600 bg-red-50 px-3 py-1.5 rounded-lg border border-red-200">{error}</div>
          )}
          <div className="flex gap-2">
            <button onClick={submit} disabled={saving}
              className="px-4 py-1.5 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-50">
              {saving ? '...' : 'إضافة'}
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
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState('general')
  const [settings,  setSettings]  = useState([])
  const [dropdowns, setDropdowns] = useState({})
  const [ddKeys,    setDdKeys]    = useState([])
  const [loading,   setLoading]   = useState(true)
  const [toast,     setToast]     = useState(null)

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3000)
  }

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [sRes, dRes, kRes] = await Promise.all([
        configApi.listSettings(),
        configApi.groupedDropdowns(),
        configApi.dropdownKeys(),
      ])
      setSettings(sRes.data)
      setDropdowns(dRes.data)
      setDdKeys(kRes.data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const filteredSettings = activeTab === 'dropdowns'
    ? []
    : settings.filter(s => s.category === activeTab)

  return (
    <div className="flex flex-col h-full bg-gray-50" dir="rtl">

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl shadow-lg text-sm font-medium transition-all
          ${toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'}`}>
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-2xl">⚙️</span>
          <div>
            <h1 className="text-xl font-bold text-gray-900">إعدادات النظام</h1>
            <p className="text-sm text-gray-500">تكوين منصة العمليات والقوائم المنسدلة</p>
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">

        {/* Sidebar */}
        <div className="w-52 bg-white border-l border-gray-200 shrink-0 py-3 px-2 space-y-0.5">
          {TABS.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors
                ${activeTab === tab.id
                  ? 'bg-brand-600 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100'}`}>
              <span className="text-base">{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </div>

        {/* Panel */}
        <div className="flex-1 overflow-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center h-48">
              <div className="text-gray-400 animate-pulse text-sm">جاري التحميل...</div>
            </div>
          ) : activeTab === 'dropdowns' ? (
            <div className="space-y-6 max-w-3xl">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-gray-900">القوائم المنسدلة</h2>
                <span className="text-sm text-gray-500 bg-gray-100 px-3 py-1 rounded-full">{ddKeys.length} قائمة</span>
              </div>
              {ddKeys.length === 0 && (
                <div className="bg-white rounded-2xl border border-gray-200 p-8 text-center text-gray-400">
                  لا توجد قوائم. قم بتشغيل <code className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">python manage.py seed_config</code> أولاً.
                </div>
              )}
              {ddKeys.map(key => (
                <div key={key} className="bg-white rounded-2xl border border-gray-200 p-5">
                  <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-100">
                    <h3 className="font-semibold text-gray-800">
                      {DROPDOWN_KEY_LABELS[key] || key}
                    </h3>
                    <span className="text-[11px] font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded">{key}</span>
                  </div>
                  <DropdownEditor
                    dropdownKey={key}
                    options={dropdowns[key] || []}
                    onRefresh={loadAll}
                  />
                </div>
              ))}
            </div>
          ) : (
            <div className="max-w-3xl">
              {filteredSettings.length === 0 ? (
                <div className="bg-white rounded-2xl border border-gray-200 p-8 text-center">
                  <div className="text-4xl mb-3">📭</div>
                  <div className="text-gray-500 text-sm">
                    لا توجد إعدادات في هذه الفئة.
                    <br />
                    قم بتشغيل <code className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded">python manage.py seed_config</code> لإنشاء الإعدادات الافتراضية.
                  </div>
                </div>
              ) : (
                <div className="bg-white rounded-2xl border border-gray-200 p-6">
                  <div className="flex items-center gap-2 mb-5 pb-4 border-b border-gray-100">
                    <span className="text-xl">{TABS.find(t => t.id === activeTab)?.icon}</span>
                    <h2 className="text-lg font-bold text-gray-900">
                      {TABS.find(t => t.id === activeTab)?.label}
                    </h2>
                    <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full mr-auto">
                      {filteredSettings.length} إعداد
                    </span>
                  </div>
                  {filteredSettings.map(s => (
                    <SettingRow key={s.id} setting={s}
                      onSaved={() => { loadAll(); showToast('تم حفظ الإعداد ✓') }} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
