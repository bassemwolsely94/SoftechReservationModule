/**
 * IncentivesPage.jsx  — v3
 *
 * Item-based sales incentive engine UI.
 *
 * Tabs:
 *   1. Programs     — list + create incentive programs
 *   2. Rules        — multi-item rules per program (CSV upload + inline item manager)
 *   3. Calculate    — pick period → run engine → preview report
 *   4. Report       — per-user aggregated table with adjustments + drill-down
 *   5. Adjustments  — manual +/- correction entries per user per period
 *   6. Settlements  — finalized payroll records with printable receipts
 *   7. History      — calculation audit log
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { incentivesApi, usersApi } from '../api/client'
import RefreshButton from '../components/RefreshButton'
import ItemSearchWidget from '../components/ItemSearchWidget'

// ── Tiny helpers ─────────────────────────────────────────────────────────────

const fmt = (n, dp = 2) =>
  Number(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })

const monthStart = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}
const monthEnd = () => {
  const d = new Date()
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0)
  return last.toISOString().slice(0, 10)
}

const INCENTIVE_TYPE_LABELS = {
  percent:               'نسبة % من صافي البيع',
  fixed:                 'مبلغ ثابت / وحدة',
  fixed_per_unit:        'مبلغ ثابت / وحدة',
  fixed_per_transaction: 'مبلغ ثابت / فاتورة',
  tiered:                'متدرج (سلاب)',
}

// ── Shared mini-components ───────────────────────────────────────────────────

function Badge({ color = 'gray', children }) {
  const palette = {
    green:  'bg-green-100 text-green-800',
    red:    'bg-red-100 text-red-800',
    blue:   'bg-blue-100 text-blue-800',
    yellow: 'bg-yellow-100 text-yellow-800',
    gray:   'bg-gray-100 text-gray-700',
    purple: 'bg-purple-100 text-purple-800',
    orange: 'bg-orange-100 text-orange-700',
    teal:   'bg-teal-100 text-teal-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${palette[color] || palette.gray}`}>
      {children}
    </span>
  )
}

function Spinner() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="w-8 h-8 border-4 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
    </div>
  )
}

function EmptyState({ icon, title, sub }) {
  return (
    <div className="text-center py-16 text-gray-400">
      <div className="text-5xl mb-3">{icon}</div>
      <div className="font-semibold text-gray-600">{title}</div>
      {sub && <div className="text-sm mt-1">{sub}</div>}
    </div>
  )
}

// ── Tab bar ───────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'programs',     label: 'البرامج',          icon: '🏆' },
  { id: 'rules',        label: 'القواعد',          icon: '📐' },
  { id: 'calculate',    label: 'الاحتساب',         icon: '⚡' },
  { id: 'report',       label: 'التقرير',          icon: '📊' },
  { id: 'near-expiry',  label: 'قريب الصلاحية',    icon: '⏰' },
  { id: 'roi',          label: 'عائد الاستثمار',   icon: '📈' },
  { id: 'suggestions',  label: 'اقتراحات ذكية',    icon: '🧠' },
  { id: 'adjustments',  label: 'تسويات يدوية',     icon: '✏️' },
  { id: 'settlements',  label: 'التسويات النهائية', icon: '✅' },
  { id: 'history',      label: 'سجل الاحتساب',     icon: '🕒' },
]

// ─────────────────────────────────────────────────────────────────────────────
// Programs tab
// ─────────────────────────────────────────────────────────────────────────────

function CreateProgramModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    name: '', description: '',
    start_date: monthStart(), end_date: monthEnd(),
    calculation_period: 'monthly', is_active: true,
    sponsor_name: '', sponsor_contribution_pct: '',
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const save = async () => {
    if (!form.name.trim()) { setErr('اسم البرنامج مطلوب'); return }
    setSaving(true); setErr('')
    try {
      const { data } = await incentivesApi.createProgram(form)
      onCreated(data)
    } catch (e) {
      setErr(e.response?.data?.detail || 'حدث خطأ')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg p-6">
        <h2 className="text-lg font-bold mb-4">برنامج حوافز جديد</h2>
        {err && <div className="mb-3 text-sm text-red-600 bg-red-50 p-2 rounded">{err}</div>}
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">اسم البرنامج *</label>
            <input className="input w-full" value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">الوصف</label>
            <textarea className="input w-full" rows={2} value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">تاريخ البداية</label>
              <input type="date" className="input w-full" value={form.start_date}
                onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">تاريخ النهاية</label>
              <input type="date" className="input w-full" value={form.end_date}
                onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))} />
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">دورة الاحتساب</label>
            <select className="input w-full" value={form.calculation_period}
              onChange={e => setForm(f => ({ ...f, calculation_period: e.target.value }))}>
              <option value="weekly">أسبوعي</option>
              <option value="monthly">شهري</option>
              <option value="custom">مخصص</option>
            </select>
          </div>
        </div>
        {/* Sponsor fields (Feature 9) */}
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 space-y-2">
          <div className="text-xs font-semibold text-amber-700 mb-1">
            برنامج برعاية مورد (اختياري)
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">اسم المورد / الراعي</label>
              <input className="input w-full" value={form.sponsor_name}
                onChange={e => setForm(f => ({ ...f, sponsor_name: e.target.value }))}
                placeholder="مثال: فايزر، نوفارتس" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">نسبة مساهمة الراعي %</label>
              <input type="number" className="input w-full" dir="ltr"
                value={form.sponsor_contribution_pct}
                onChange={e => setForm(f => ({ ...f, sponsor_contribution_pct: e.target.value }))}
                min="0" max="100" step="1" placeholder="0–100" />
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-5">
          <button className="btn-secondary" onClick={onClose}>إلغاء</button>
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'جارٍ الحفظ...' : 'إنشاء البرنامج'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ProgramsTab({ selectedProgram, onSelect }) {
  const [programs, setPrograms]     = useState([])
  const [loading, setLoading]       = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [cloningId, setCloningId]   = useState(null)
  const [showCloneModal, setShowCloneModal] = useState(null) // program to clone

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await incentivesApi.listPrograms()
      setPrograms(data.results || data)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-bold text-gray-700">برامج الحوافز</h2>
        <button className="btn-primary text-sm" onClick={() => setShowCreate(true)}>+ برنامج جديد</button>
      </div>

      {loading ? <Spinner /> : programs.length === 0 ? (
        <EmptyState icon="🏆" title="لا توجد برامج حوافز" sub="أنشئ برنامجاً جديداً للبدء" />
      ) : (
        <div className="space-y-3">
          {programs.map(p => (
            <div key={p.id} onClick={() => onSelect(p)}
              className={`rounded-xl border p-4 cursor-pointer transition-all ${
                selectedProgram?.id === p.id
                  ? 'border-brand-500 bg-brand-50 shadow-sm'
                  : 'border-gray-200 bg-white hover:border-brand-300 hover:shadow-sm'
              }`}>
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold text-gray-800">{p.name}</div>
                  {p.description && <div className="text-xs text-gray-500 mt-0.5">{p.description}</div>}
                  <div className="flex flex-wrap items-center gap-2 mt-2 text-xs text-gray-500">
                    <span>📅 {p.start_date} → {p.end_date}</span>
                    <span>·</span>
                    <span>📐 {p.rule_count} قاعدة</span>
                    {p.is_sponsored && (
                      <Badge color="yellow">🤝 {p.sponsor_name}</Badge>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    className="text-xs text-brand-600 hover:text-brand-700 border border-brand-200 rounded-lg px-2 py-1 hover:bg-brand-50"
                    onClick={e => { e.stopPropagation(); setShowCloneModal(p) }}
                  >
                    نسخ
                  </button>
                  <Badge color={p.is_active ? 'green' : 'gray'}>{p.is_active ? 'نشط' : 'موقف'}</Badge>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <CreateProgramModal
          onClose={() => setShowCreate(false)}
          onCreated={p => { setShowCreate(false); load(); onSelect(p) }}
        />
      )}

      {showCloneModal && (
        <CloneProgramModal
          source={showCloneModal}
          onClose={() => setShowCloneModal(null)}
          onCloned={p => { setShowCloneModal(null); load(); onSelect(p) }}
        />
      )}
    </div>
  )
}

function CloneProgramModal({ source, onClose, onCloned }) {
  const nextMonthStart = () => {
    const d = new Date()
    d.setMonth(d.getMonth() + 1, 1)
    return d.toISOString().slice(0, 10)
  }
  const nextMonthEnd = () => {
    const d = new Date()
    d.setMonth(d.getMonth() + 2, 0)
    return d.toISOString().slice(0, 10)
  }
  const [form, setForm] = useState({
    new_name: '',
    new_start_date: nextMonthStart(),
    new_end_date: nextMonthEnd(),
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const save = async () => {
    setSaving(true); setErr('')
    try {
      const { data } = await incentivesApi.cloneProgram(source.id, {
        new_name:       form.new_name || undefined,
        new_start_date: form.new_start_date,
        new_end_date:   form.new_end_date,
      })
      onCloned(data)
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل النسخ')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <h2 className="text-lg font-bold mb-1">نسخ البرنامج</h2>
        <p className="text-sm text-gray-500 mb-4">نسخ من: <strong>{source.name}</strong> ({source.rule_count} قاعدة)</p>
        {err && <div className="mb-3 text-sm text-red-600 bg-red-50 p-2 rounded">{err}</div>}
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 mb-1 block">اسم البرنامج الجديد (اختياري)</label>
            <input className="input w-full" value={form.new_name}
              onChange={e => setForm(f => ({ ...f, new_name: e.target.value }))}
              placeholder={`نسخة من ${source.name}`} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">تاريخ البداية</label>
              <input type="date" className="input w-full" value={form.new_start_date}
                onChange={e => setForm(f => ({ ...f, new_start_date: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">تاريخ النهاية</label>
              <input type="date" className="input w-full" value={form.new_end_date}
                onChange={e => setForm(f => ({ ...f, new_end_date: e.target.value }))} />
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-5">
          <button className="btn-secondary" onClick={onClose}>إلغاء</button>
          <button className="btn-primary" onClick={save} disabled={saving}>
            {saving ? 'جارٍ النسخ...' : 'نسخ البرنامج'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Slab config editor (for tiered incentive type)
// ─────────────────────────────────────────────────────────────────────────────

const BLANK_SLAB = { min_qty: 0, max_qty: null, rate: 0 }

function SlabEditor({ value, onChange }) {
  // value = { type: 'percent'|'fixed_per_unit', slabs: [...] }
  const config = value || { type: 'percent', slabs: [{ ...BLANK_SLAB }] }
  const slabs  = config.slabs || []

  const updSlab = (idx, field, val) => {
    const next = slabs.map((s, i) => i === idx ? { ...s, [field]: val === '' ? null : Number(val) } : s)
    onChange({ ...config, slabs: next })
  }
  const addSlab = () => onChange({ ...config, slabs: [...slabs, { ...BLANK_SLAB }] })
  const delSlab = (idx) => onChange({ ...config, slabs: slabs.filter((_, i) => i !== idx) })

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-amber-800">إعداد السلاب المتدرج</span>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-600">نوع السلاب:</label>
          <select
            className="text-xs border border-amber-300 rounded px-1.5 py-0.5 bg-white"
            value={config.type}
            onChange={e => onChange({ ...config, type: e.target.value })}
          >
            <option value="percent">نسبة %</option>
            <option value="fixed_per_unit">مبلغ ثابت / وحدة</option>
          </select>
        </div>
      </div>
      <div className="text-xs text-amber-700 bg-amber-100 rounded px-2 py-1">
        السعر يُطبَّق على إجمالي الكميات في الفترة (وليس تصاعدياً) — اترك الحد الأقصى فارغاً للسلاب الأخير.
      </div>
      <div className="space-y-2">
        {slabs.map((slab, idx) => (
          <div key={idx} className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-4 text-center">{idx + 1}</span>
            <div className="flex-1 grid grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] text-gray-400">من (وحدة)</label>
                <input type="number" className="input w-full text-xs" dir="ltr"
                  value={slab.min_qty ?? ''}
                  onChange={e => updSlab(idx, 'min_qty', e.target.value)}
                  min="0" step="1" />
              </div>
              <div>
                <label className="text-[10px] text-gray-400">إلى (وحدة، فارغ=∞)</label>
                <input type="number" className="input w-full text-xs" dir="ltr"
                  value={slab.max_qty ?? ''}
                  onChange={e => updSlab(idx, 'max_qty', e.target.value)}
                  min="0" step="1" placeholder="∞" />
              </div>
              <div>
                <label className="text-[10px] text-gray-400">
                  السعر ({config.type === 'percent' ? '%' : 'ج.م/وحدة'})
                </label>
                <input type="number" className="input w-full text-xs" dir="ltr"
                  value={slab.rate ?? ''}
                  onChange={e => updSlab(idx, 'rate', e.target.value)}
                  min="0" step="0.01" />
              </div>
            </div>
            <button className="text-red-400 hover:text-red-600 text-xs flex-shrink-0"
              onClick={() => delSlab(idx)} title="حذف السلاب">✕</button>
          </div>
        ))}
      </div>
      <button
        className="text-xs text-amber-700 border border-amber-300 hover:bg-amber-100 px-2 py-1 rounded"
        onClick={addSlab}
      >+ إضافة نطاق</button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Rule Items Manager — inline panel inside rule card
// ─────────────────────────────────────────────────────────────────────────────

function RuleItemsManager({ rule, onItemsChanged }) {
  const [items, setItems]         = useState(rule.rule_items || [])
  const [adding, setAdding]       = useState(false)
  const [manualCode, setManualCode] = useState('')
  const [manualName, setManualName] = useState('')
  const [manualOv, setManualOv]   = useState('')
  const [busy, setBusy]           = useState(false)
  const [err, setErr]             = useState('')

  const [csvMode, setCsvMode]     = useState('replace')
  const [csvUploading, setCsvUploading] = useState(false)
  const [csvMsg, setCsvMsg]       = useState('')
  const csvRef = useRef()

  const reload = async () => {
    const { data } = await incentivesApi.getRule(rule.id)
    const updated = data.rule_items || []
    setItems(updated)
    onItemsChanged(data)
  }

  const addItem = async (itemCode, itemName, overrideVal) => {
    setErr(''); setBusy(true)
    try {
      await incentivesApi.addRuleItem(rule.id, {
        item_code: itemCode,
        item_name: itemName,
        incentive_override: overrideVal !== '' ? overrideVal : null,
      })
      await reload()
      setManualCode(''); setManualName(''); setManualOv('')
      setAdding(false)
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل الإضافة')
    } finally { setBusy(false) }
  }

  const removeItem = async (itemCode) => {
    setBusy(true)
    try {
      await incentivesApi.removeRuleItem(rule.id, itemCode)
      const next = items.filter(i => i.item_code !== itemCode)
      setItems(next)
      onItemsChanged({ ...rule, rule_items: next })
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل الحذف')
    } finally { setBusy(false) }
  }

  const clearAll = async () => {
    if (!window.confirm(`حذف كل الأصناف (${items.length}) من هذه القاعدة؟`)) return
    setBusy(true)
    try {
      await incentivesApi.clearRuleItems(rule.id)
      setItems([])
      onItemsChanged({ ...rule, rule_items: [] })
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل الحذف')
    } finally { setBusy(false) }
  }

  const handleCsvUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setCsvUploading(true); setCsvMsg('')
    const fd = new FormData()
    fd.append('csv_file', file)
    fd.append('mode', csvMode)
    try {
      const { data } = await incentivesApi.importRuleItemsCsv(rule.id, fd)
      setCsvMsg(`✅ تم الاستيراد: أُضيف ${data.created}، حُدِّث ${data.updated}، حُذف ${data.deleted}. الإجمالي: ${data.total}`)
      await reload()
    } catch (er) {
      setCsvMsg(`❌ ${er.response?.data?.detail || 'فشل الاستيراد'}`)
    } finally {
      setCsvUploading(false)
      e.target.value = ''
    }
  }

  const isPercent = rule.incentive_type === 'percent'

  return (
    <div className="mt-3 border-t border-dashed border-gray-200 pt-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-500">
          الأصناف المُستهدفة ({items.length})
        </span>
        <div className="flex items-center gap-1.5 flex-wrap justify-end">
          {items.length > 0 && (
            <button
              className="text-xs text-red-500 hover:text-red-700 px-2 py-0.5 border border-red-200 rounded"
              onClick={clearAll} disabled={busy}
            >حذف الكل</button>
          )}
          <button
            className="text-xs text-brand-600 hover:text-brand-800 px-2 py-0.5 border border-brand-200 rounded"
            onClick={() => setAdding(a => !a)}
          >{adding ? 'إلغاء' : '+ إضافة صنف'}</button>
        </div>
      </div>

      {err && <div className="text-xs text-red-600 bg-red-50 px-2 py-1 rounded">{err}</div>}

      {adding && (
        <div className="bg-gray-50 rounded-xl p-3 space-y-2">
          <div className="text-xs font-semibold text-gray-600 mb-1">إضافة صنف عبر بحث الكتالوج</div>
          {/* Pass selected=null always so widget resets after each pick */}
          <ItemSearchWidget
            selected={null}
            onSelect={item => {
              setManualCode(item.softech_id || String(item.id))
              setManualName(item.name || '')
            }}
            onClear={() => {}}
            placeholder="ابحث باسم الصنف أو الكود أو الباركود..."
          />
          <div className="grid grid-cols-3 gap-2 mt-1">
            <div>
              <label className="text-xs text-gray-400">كود الصنف</label>
              <input className="input w-full text-xs" dir="ltr" value={manualCode}
                onChange={e => setManualCode(e.target.value)} placeholder="يدوي أو من البحث" />
            </div>
            <div>
              <label className="text-xs text-gray-400">اسم الصنف</label>
              <input className="input w-full text-xs" value={manualName}
                onChange={e => setManualName(e.target.value)} placeholder="اختياري" />
            </div>
            <div>
              <label className="text-xs text-gray-400">حافز خاص (override)</label>
              <input type="number" className="input w-full text-xs" dir="ltr" value={manualOv}
                onChange={e => setManualOv(e.target.value)}
                placeholder={`فارغ = ${rule.incentive_value}${isPercent ? '%' : ' ج.م'}`}
                step="0.01" min="0" />
            </div>
          </div>
          <div className="flex justify-end">
            <button
              className="btn-primary text-xs py-1 px-3"
              disabled={!manualCode.trim() || busy}
              onClick={() => addItem(manualCode.trim(), manualName.trim(), manualOv)}
            >{busy ? '...' : 'إضافة'}</button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs text-gray-400">استيراد CSV:</span>
        <select
          className="text-xs border border-gray-200 rounded px-1 py-0.5"
          value={csvMode} onChange={e => setCsvMode(e.target.value)}
        >
          <option value="replace">استبدال الكل</option>
          <option value="append">إضافة للموجود</option>
        </select>
        <button
          className="text-xs text-purple-600 hover:text-purple-800 px-2 py-0.5 border border-purple-200 rounded"
          onClick={() => csvRef.current?.click()}
          disabled={csvUploading}
        >
          {csvUploading ? 'جارٍ الاستيراد...' : '📂 رفع CSV'}
        </button>
        <input ref={csvRef} type="file" accept=".csv,text/csv" className="hidden"
          onChange={handleCsvUpload} />
        <button
          className="text-xs text-gray-400 hover:text-gray-600 underline"
          onClick={() => {
            const csv = 'item_code,item_name,incentive_override\n1001,مثال صنف 1,\n1002,مثال صنف 2,5.5\n'
            const a = document.createElement('a')
            a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv)
            a.download = 'incentive_items_template.csv'
            a.click()
          }}
        >تحميل نموذج CSV</button>
      </div>
      {csvMsg && <div className="text-xs text-gray-600 bg-gray-50 px-2 py-1 rounded">{csvMsg}</div>}

      {items.length > 0 && (
        <div className="rounded-xl border border-gray-100 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-2 py-1.5 text-right text-gray-500 font-medium">كود الصنف</th>
                <th className="px-2 py-1.5 text-right text-gray-500 font-medium">الاسم</th>
                <th className="px-2 py-1.5 text-right text-gray-500 font-medium">حافز خاص</th>
                <th className="px-2 py-1.5 w-8" />
              </tr>
            </thead>
            <tbody>
              {items.map(ri => (
                <tr key={ri.item_code} className="border-t border-gray-100 hover:bg-gray-50">
                  <td className="px-2 py-1.5 font-mono">{ri.item_code}</td>
                  <td className="px-2 py-1.5 text-gray-600 max-w-[180px] break-words">{ri.item_name || '—'}</td>
                  <td className="px-2 py-1.5 text-right">
                    {ri.incentive_override != null
                      ? <Badge color="orange">{ri.incentive_override}{isPercent ? '%' : ' ج.م'}</Badge>
                      : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <button
                      className="text-red-400 hover:text-red-600 text-xs"
                      onClick={() => removeItem(ri.item_code)} disabled={busy}
                    >✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {items.length === 0 && (
        <div className="text-xs text-gray-400 py-2 text-center bg-gray-50 rounded-lg">
          لا توجد أصناف — أضف أصنافاً يدوياً أو استورد CSV
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Rule Form (create / edit) — v3: all types + slab editor + new conditions
// ─────────────────────────────────────────────────────────────────────────────

function RuleForm({ programId, rule, onSaved, onCancel }) {
  const blank = {
    program: programId,
    rule_name: '',
    item_code: '',
    item_name: '',
    incentive_type: 'percent',
    incentive_value: '',
    slab_config: null,
    min_qty: '0',
    min_total_qty_in_period: '',
    person_code_filter: '',
    branch_filter: '',
    time_window_start: '',
    time_window_end: '',
    // ── Target-based ─────────────────────────────────────────────────────
    target_qty: '',
    target_tiers: null,
    // ── Near-expiry filters ──────────────────────────────────────────────
    expiry_within_days: '',
    is_imported_filter: 'any',
    origin_codes: '',         // stored as comma-separated string in UI, converted on save
    margin_min: '',
    margin_max: '',
    pack_price_min: '',
    pack_price_max: '',
    // ────────────────────────────────────────────────────────────────────
    priority: '0',
    is_active: true,
  }
  const [form, setForm]   = useState(() => {
    if (!rule) return blank
    // Convert origin_codes array → comma string for the text input
    const originStr = Array.isArray(rule.origin_codes)
      ? rule.origin_codes.join(', ')
      : (rule.origin_codes || '')
    return { ...blank, ...rule, origin_codes: originStr }
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr]     = useState('')

  const upd = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const isTiered  = form.incentive_type === 'tiered'
  const isPercent = form.incentive_type === 'percent'
  const isPerTx   = form.incentive_type === 'fixed_per_transaction'

  const incentiveValueLabel = {
    percent:               'النسبة (%)',
    fixed:                 'المبلغ / وحدة (ج.م)',
    fixed_per_unit:        'المبلغ / وحدة (ج.م)',
    fixed_per_transaction: 'المبلغ / فاتورة (ج.م)',
    tiered:                'قيمة افتراضية (لا تُستخدم في السلاب)',
  }

  const save = async () => {
    if (!isTiered && !form.incentive_value) { setErr('قيمة الحافز مطلوبة'); return }
    if (isTiered && (!form.slab_config?.slabs?.length)) { setErr('أضف سلاباً واحداً على الأقل'); return }
    setSaving(true); setErr('')
    try {
      // Convert origin_codes: "1,2,5" → ["1","2","5"] or null
      const originCodesArr = (form.origin_codes || '')
        .split(',')
        .map(s => s.trim())
        .filter(Boolean)

      const payload = {
        ...form,
        program: programId,
        incentive_value:           Number(form.incentive_value || 0),
        min_qty:                   Number(form.min_qty || 0),
        min_total_qty_in_period:   form.min_total_qty_in_period ? Number(form.min_total_qty_in_period) : null,
        priority:                  Number(form.priority || 0),
        expiry_within_days:        form.expiry_within_days ? Number(form.expiry_within_days) : null,
        time_window_start:         form.time_window_start || null,
        time_window_end:           form.time_window_end   || null,
        branch_filter:             form.branch_filter || '',
        slab_config:               isTiered ? form.slab_config : null,
        // Target-based
        target_qty:                form.target_qty !== '' ? Number(form.target_qty) : null,
        target_tiers:              form.target_tiers || null,
        // Near-expiry
        is_imported_filter:        form.is_imported_filter || 'any',
        origin_codes:              originCodesArr.length ? originCodesArr : null,
        margin_min:                form.margin_min !== '' ? Number(form.margin_min) : null,
        margin_max:                form.margin_max !== '' ? Number(form.margin_max) : null,
        pack_price_min:            form.pack_price_min !== '' ? Number(form.pack_price_min) : null,
        pack_price_max:            form.pack_price_max !== '' ? Number(form.pack_price_max) : null,
      }
      delete payload.rule_items
      delete payload.item_count
      delete payload.is_near_expiry_rule
      const res = rule?.id
        ? await incentivesApi.updateRule(rule.id, payload)
        : await incentivesApi.createRule(payload)
      onSaved(res.data)
    } catch (e) {
      setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'حدث خطأ')
    } finally { setSaving(false) }
  }

  return (
    <div className="bg-white border border-brand-200 rounded-xl p-4 space-y-3">
      {err && <div className="text-sm text-red-600 bg-red-50 p-2 rounded">{err}</div>}

      {/* Name */}
      <div>
        <label className="text-xs text-gray-500 mb-1 block">اسم القاعدة (للعرض)</label>
        <input className="input w-full" value={form.rule_name}
          onChange={e => upd('rule_name', e.target.value)} placeholder="مثال: عروض رمضان" />
      </div>

      {/* Legacy single-item */}
      <div className="bg-gray-50 rounded-lg p-3 space-y-2">
        <div className="text-xs text-gray-400 font-medium mb-1">
          صنف وحيد (اختياري — اتركه فارغاً إذا كنت تستخدم قائمة الأصناف أدناه)
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs text-gray-500 mb-0.5 block">كود الصنف</label>
            <input className="input w-full" dir="ltr" value={form.item_code}
              onChange={e => upd('item_code', e.target.value)} placeholder="1234" />
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-0.5 block">اسم الصنف</label>
            <input className="input w-full" value={form.item_name}
              onChange={e => upd('item_name', e.target.value)} placeholder="أوجمنتين 625" />
          </div>
        </div>
      </div>

      {/* Incentive type + value */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">نوع الحافز</label>
          <select className="input w-full" value={form.incentive_type}
            onChange={e => upd('incentive_type', e.target.value)}>
            <option value="percent">نسبة مئوية % من صافي البيع</option>
            <option value="fixed_per_unit">مبلغ ثابت / وحدة</option>
            <option value="fixed_per_transaction">مبلغ ثابت / فاتورة</option>
            <option value="tiered">متدرج (سلاب)</option>
            <option value="target_based">قائم على الهدف</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">
            {incentiveValueLabel[form.incentive_type] || 'القيمة'}
          </label>
          <input type="number" className="input w-full" value={form.incentive_value}
            onChange={e => upd('incentive_value', e.target.value)}
            step="0.01" min="0" dir="ltr"
            disabled={isTiered}
            placeholder={isTiered ? 'يُحدَّد في السلاب' : '0.00'} />
        </div>
      </div>

      {/* Slab editor */}
      {isTiered && (
        <SlabEditor
          value={form.slab_config}
          onChange={v => upd('slab_config', v)}
        />
      )}

      {/* Target-based config (Feature 2) */}
      {form.incentive_type === 'target_based' && (
        <div className="bg-purple-50 border border-purple-200 rounded-xl p-3 space-y-2">
          <div className="text-xs font-semibold text-purple-700 mb-1">
            إعداد الهدف الكمي
          </div>
          <div>
            <label className="text-xs text-gray-500 mb-1 block">
              الهدف الكمي (وحدة لكل مندوب لكل فترة)
            </label>
            <input type="number" className="input w-full" dir="ltr"
              value={form.target_qty}
              onChange={e => upd('target_qty', e.target.value)}
              min="1" step="1" placeholder="مثال: 200" />
          </div>
          <div className="text-xs text-gray-500 mt-1">
            شرائح الإنجاز تُعرَّف تلقائياً. للتخصيص المتقدم استخدم JSON مباشرة.
          </div>
        </div>
      )}

      {/* Conditions row 1 */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">الحد الأدنى للكمية / فاتورة</label>
          <input type="number" className="input w-full" value={form.min_qty}
            onChange={e => upd('min_qty', e.target.value)} step="1" min="0" dir="ltr" />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">الحد الأدنى لإجمالي الكمية / فترة</label>
          <input type="number" className="input w-full" value={form.min_total_qty_in_period}
            onChange={e => upd('min_total_qty_in_period', e.target.value)}
            step="1" min="0" dir="ltr" placeholder="فارغ = لا قيد" />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">أيام الصلاحية (اختياري)</label>
          <input type="number" className="input w-full" value={form.expiry_within_days}
            onChange={e => upd('expiry_within_days', e.target.value)}
            step="1" min="1" dir="ltr" placeholder="فارغ = لا قيد" />
        </div>
      </div>

      {/* Near-expiry extended filters — shown when expiry_within_days is set */}
      {form.expiry_within_days > 0 && (
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-3 space-y-3">
          <div className="text-xs font-semibold text-orange-700 mb-1">
            فلاتر الصلاحية المتقدمة (اختيارية)
          </div>

          {/* Origin filter */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">فلتر المصدر</label>
              <select className="input w-full" value={form.is_imported_filter}
                onChange={e => upd('is_imported_filter', e.target.value)}>
                <option value="any">الكل (محلي + مستورد)</option>
                <option value="local">محلي فقط</option>
                <option value="imported">مستورد فقط</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">
                كودات المنشأ (مفصولة بفاصلة)
              </label>
              <input className="input w-full" dir="ltr"
                value={form.origin_codes}
                onChange={e => upd('origin_codes', e.target.value)}
                placeholder="فارغ = كل المنشآت، مثال: 1,2,5" />
            </div>
          </div>

          {/* Margin filter */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">هامش الربح الأدنى %</label>
              <input type="number" className="input w-full" dir="ltr"
                value={form.margin_min}
                onChange={e => upd('margin_min', e.target.value)}
                step="0.1" min="0" max="100" placeholder="فارغ = لا قيد" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">هامش الربح الأقصى %</label>
              <input type="number" className="input w-full" dir="ltr"
                value={form.margin_max}
                onChange={e => upd('margin_max', e.target.value)}
                step="0.1" min="0" max="100" placeholder="فارغ = لا قيد" />
            </div>
          </div>

          {/* Pack price filter */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">سعر العبوة الأدنى (ج.م)</label>
              <input type="number" className="input w-full" dir="ltr"
                value={form.pack_price_min}
                onChange={e => upd('pack_price_min', e.target.value)}
                step="1" min="0" placeholder="فارغ = لا قيد" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">سعر العبوة الأقصى (ج.م)</label>
              <input type="number" className="input w-full" dir="ltr"
                value={form.pack_price_max}
                onChange={e => upd('pack_price_max', e.target.value)}
                step="1" min="0" placeholder="فارغ = لا قيد" />
            </div>
          </div>
        </div>
      )}

      {/* Conditions row 2 */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">فلتر كود المندوب</label>
          <input className="input w-full" value={form.person_code_filter}
            onChange={e => upd('person_code_filter', e.target.value)} dir="ltr"
            placeholder="فارغ = الكل" />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">فلتر الفرع (branchcode)</label>
          <input className="input w-full" value={form.branch_filter}
            onChange={e => upd('branch_filter', e.target.value)} dir="ltr"
            placeholder="فارغ = كل الفروع" />
        </div>
      </div>

      {/* Time window */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">بداية النافذة الزمنية (HH:MM)</label>
          <input type="time" className="input w-full" value={form.time_window_start}
            onChange={e => upd('time_window_start', e.target.value)} dir="ltr" />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">نهاية النافذة الزمنية (HH:MM)</label>
          <input type="time" className="input w-full" value={form.time_window_end}
            onChange={e => upd('time_window_end', e.target.value)} dir="ltr" />
        </div>
      </div>

      {/* Priority + active */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">الأولوية (الأصغر = أعلى أولوية)</label>
          <input type="number" className="input w-full" value={form.priority}
            onChange={e => upd('priority', e.target.value)} step="1" min="0" dir="ltr" />
        </div>
        <div className="flex items-end pb-1">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={form.is_active}
              onChange={e => upd('is_active', e.target.checked)} />
            <span className="text-sm">قاعدة نشطة</span>
          </label>
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <button className="btn-secondary text-sm" onClick={onCancel}>إلغاء</button>
        <button className="btn-primary text-sm" onClick={save} disabled={saving}>
          {saving ? 'جارٍ الحفظ...' : rule?.id ? 'حفظ التعديلات' : 'إضافة القاعدة'}
        </button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Rules tab
// ─────────────────────────────────────────────────────────────────────────────

function ruleBadgeColor(type) {
  switch (type) {
    case 'percent': return 'green'
    case 'fixed_per_unit': case 'fixed': return 'yellow'
    case 'fixed_per_transaction': return 'blue'
    case 'tiered': return 'purple'
    default: return 'gray'
  }
}

function RulesTab({ selectedProgram }) {
  const [rules, setRules]         = useState([])
  const [loading, setLoading]     = useState(false)
  const [addingNew, setAddingNew] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [expandedId, setExpandedId] = useState(null)

  const load = useCallback(async () => {
    if (!selectedProgram) return
    setLoading(true)
    try {
      const { data } = await incentivesApi.listRules({ program: selectedProgram.id })
      setRules(data.results || data)
    } finally { setLoading(false) }
  }, [selectedProgram])

  useEffect(() => { load() }, [load])

  const deleteRule = async (id) => {
    if (!window.confirm('هل تريد حذف هذه القاعدة؟')) return
    await incentivesApi.deleteRule(id)
    setRules(rs => rs.filter(r => r.id !== id))
  }

  if (!selectedProgram) return (
    <EmptyState icon="📐" title="اختر برنامجاً أولاً" sub="اذهب إلى تبويب البرامج واختر برنامجاً" />
  )

  const ruleValueDisplay = (r) => {
    if (r.incentive_type === 'tiered') {
      const slabCount = r.slab_config?.slabs?.length || 0
      return `سلاب (${slabCount} نطاق)`
    }
    if (r.incentive_type === 'percent') return `${r.incentive_value}%`
    if (r.incentive_type === 'fixed_per_transaction') return `${fmt(r.incentive_value)} ج.م/فاتورة`
    return `${fmt(r.incentive_value)} ج.م/وحدة`
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-bold text-gray-700">قواعد الحوافز</h2>
          <div className="text-xs text-gray-500">{selectedProgram.name}</div>
        </div>
        <button className="btn-primary text-sm" onClick={() => { setAddingNew(true); setEditingId(null) }}>
          + قاعدة جديدة
        </button>
      </div>

      {addingNew && (
        <div className="mb-4">
          <RuleForm
            programId={selectedProgram.id}
            onSaved={r => { setAddingNew(false); setRules(rs => [r, ...rs]); setExpandedId(r.id) }}
            onCancel={() => setAddingNew(false)}
          />
        </div>
      )}

      {loading ? <Spinner /> : rules.length === 0 ? (
        <EmptyState icon="📐" title="لا توجد قواعد" sub="أضف قاعدة حوافز للبدء" />
      ) : (
        <div className="space-y-3">
          {rules.map(r => (
            <div key={r.id}>
              {editingId === r.id ? (
                <RuleForm
                  programId={selectedProgram.id}
                  rule={r}
                  onSaved={updated => {
                    setRules(rs => rs.map(x => x.id === updated.id ? updated : x))
                    setEditingId(null)
                  }}
                  onCancel={() => setEditingId(null)}
                />
              ) : (
                <div className="bg-white border border-gray-200 rounded-xl p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-gray-800">
                        {r.rule_name || r.item_name || r.item_code || '(بدون اسم)'}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                        {r.item_code && <Badge color="blue">صنف واحد: {r.item_code}</Badge>}
                        {(r.item_count > 0 || r.rule_items?.length > 0) && (
                          <Badge color="purple">
                            {r.item_count || r.rule_items?.length} صنف
                          </Badge>
                        )}
                        <Badge color={ruleBadgeColor(r.incentive_type)}>
                          {INCENTIVE_TYPE_LABELS[r.incentive_type] || r.incentive_type}: {ruleValueDisplay(r)}
                        </Badge>
                        {Number(r.min_qty) > 0 && <Badge color="gray">حد أدنى/فاتورة: {r.min_qty}</Badge>}
                        {r.min_total_qty_in_period && <Badge color="teal">حد أدنى/فترة: {r.min_total_qty_in_period}</Badge>}
                        {r.person_code_filter && <Badge color="gray">مندوب: {r.person_code_filter}</Badge>}
                        {r.branch_filter && <Badge color="gray">فرع: {r.branch_filter}</Badge>}
                        {r.time_window_start && <Badge color="gray">🕐 {r.time_window_start}→{r.time_window_end}</Badge>}
                        {r.expiry_within_days && <Badge color="red">صلاحية &lt; {r.expiry_within_days} يوم</Badge>}
                        {r.is_imported_filter === 'local'    && <Badge color="teal">محلي فقط</Badge>}
                        {r.is_imported_filter === 'imported' && <Badge color="blue">مستورد فقط</Badge>}
                        {r.margin_min != null && <Badge color="yellow">هامش &gt;= {r.margin_min}%</Badge>}
                        {r.margin_max != null && <Badge color="yellow">هامش &lt;= {r.margin_max}%</Badge>}
                        {r.pack_price_min != null && <Badge color="orange">سعر &gt;= {r.pack_price_min}</Badge>}
                        {r.pack_price_max != null && <Badge color="orange">سعر &lt;= {r.pack_price_max}</Badge>}
                        {r.is_near_expiry_rule && <Badge color="orange">قاعدة صلاحية قريبة</Badge>}
                        <Badge color="gray">أولوية: {r.priority}</Badge>
                        {!r.is_active && <Badge color="red">موقفة</Badge>}
                      </div>
                    </div>
                    <div className="flex gap-1 flex-shrink-0 mr-2">
                      <button
                        className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                          expandedId === r.id
                            ? 'text-purple-700 border-purple-300 bg-purple-50'
                            : 'text-purple-600 border-purple-200 hover:bg-purple-50'
                        }`}
                        onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
                      >
                        {expandedId === r.id ? '▲ الأصناف' : `▼ الأصناف (${r.item_count ?? r.rule_items?.length ?? 0})`}
                      </button>
                      <button className="text-xs text-blue-600 hover:text-blue-800 px-2"
                        onClick={() => setEditingId(r.id)}>تعديل</button>
                      <button className="text-xs text-red-500 hover:text-red-700 px-2"
                        onClick={() => deleteRule(r.id)}>حذف</button>
                    </div>
                  </div>

                  {expandedId === r.id && (
                    <RuleItemsManager
                      key={`rim-${r.id}`}
                      rule={r}
                      onItemsChanged={updated =>
                        setRules(rs => rs.map(x => x.id === r.id ? { ...x, ...updated } : x))
                      }
                    />
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Calculate tab — v3: user names from user_summaries, log_id display
// ─────────────────────────────────────────────────────────────────────────────

function CalculateTab({ selectedProgram }) {
  const [form, setForm] = useState({ period_start: monthStart(), period_end: monthEnd() })
  const [force,   setForce]   = useState(false)
  const [running, setRunning] = useState(false)
  const [simming, setSimming] = useState(false)
  const [result,  setResult]  = useState(null)
  const [err,     setErr]     = useState('')
  const [locked,  setLocked]  = useState(false)

  const _exec = async (simulate) => {
    if (!selectedProgram) { setErr('اختر برنامجاً أولاً'); return }
    simulate ? setSimming(true) : setRunning(true)
    setErr(''); setResult(null); setLocked(false)
    try {
      const apiCall = simulate ? incentivesApi.simulate : incentivesApi.calculate
      const { data } = await apiCall(selectedProgram.id, {
        period_start: form.period_start,
        period_end:   form.period_end,
        ...((!simulate && force) ? { force: true } : {}),
      })
      setResult(data)
      if (!simulate) setForce(false)
    } catch (e) {
      if (!simulate && e.response?.status === 409) {
        setLocked(true)
        setErr(e.response?.data?.detail || 'الفترة تحتوي على تسويات مُغلقة.')
      } else {
        setErr(e.response?.data?.detail || (simulate ? 'فشلت المحاكاة' : 'فشل الاحتساب'))
      }
    } finally { setRunning(false); setSimming(false) }
  }

  // user_summaries: [{user_id, user_name, person_code, total}]
  const summaries = result?.user_summaries
    ? [...result.user_summaries].sort((a, b) => b.total - a.total)
    : result?.total_by_user
      ? Object.entries(result.total_by_user)
          .map(([uid, total]) => ({ user_id: uid, user_name: `مندوب #${uid}`, person_code: '', total }))
          .sort((a, b) => b.total - a.total)
      : []

  return (
    <div className="space-y-5">
      <div>
        <h2 className="font-bold text-gray-700 mb-3">تشغيل الاحتساب</h2>

        {!selectedProgram && (
          <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3">
            ⚠ اختر برنامجاً من تبويب البرامج أولاً
          </div>
        )}
        {selectedProgram && (
          <div className="text-sm text-brand-700 bg-brand-50 border border-brand-200 rounded-lg p-3 mb-3">
            البرنامج: <strong>{selectedProgram.name}</strong>
          </div>
        )}

        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-4">
          {err && (
            <div className={`text-sm p-3 rounded-lg border ${locked
              ? 'text-orange-800 bg-orange-50 border-orange-200'
              : 'text-red-600 bg-red-50 border-red-200'}`}>
              {err}
              {locked && (
                <div className="mt-2 flex items-center gap-2">
                  <input id="force-cb" type="checkbox" checked={force}
                    onChange={e => setForce(e.target.checked)}
                    className="w-4 h-4 rounded accent-orange-600" />
                  <label htmlFor="force-cb" className="text-sm font-medium cursor-pointer">
                    إعادة الاحتساب بالقوة (تجاوز القفل)
                  </label>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">بداية الفترة</label>
              <input type="date" className="input w-full" value={form.period_start}
                onChange={e => setForm(f => ({ ...f, period_start: e.target.value }))} />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">نهاية الفترة</label>
              <input type="date" className="input w-full" value={form.period_end}
                onChange={e => setForm(f => ({ ...f, period_end: e.target.value }))} />
            </div>
          </div>

          <div className="flex gap-3 pt-1">
            <button
              className="flex-1 border border-brand-400 text-brand-700 hover:bg-brand-50 rounded-lg py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
              onClick={() => _exec(true)} disabled={running || simming || !selectedProgram}>
              {simming ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-3.5 h-3.5 border-2 border-brand-300 border-t-brand-700 rounded-full animate-spin" />
                  محاكاة...
                </span>
              ) : '🔍 معاينة (محاكاة)'}
            </button>
            <button
              className="flex-[2] btn-primary py-2.5 disabled:opacity-50"
              onClick={() => _exec(false)}
              disabled={running || simming || !selectedProgram || (locked && !force)}>
              {running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                  جارٍ الاحتساب...
                </span>
              ) : force ? '⚡ إعادة الاحتساب (بالقوة)' : '⚡ تشغيل الاحتساب'}
            </button>
          </div>
        </div>
      </div>

      {result && (
        <div>
          <div className="flex items-center gap-3 mb-3 flex-wrap">
            <h3 className="font-semibold text-gray-700">
              {result.simulated ? '🔍 نتائج المحاكاة (لم تُحفظ)' : '✅ نتائج الاحتساب'}
            </h3>
            <Badge color={result.simulated ? 'purple' : 'green'}>{result.created} حركة</Badge>
            {result.simulated && <Badge color="yellow">محاكاة فقط</Badge>}
            {result.log_id && (
              <span className="text-xs text-gray-400">سجل #{result.log_id}</span>
            )}
          </div>

          {result.skipped_person_codes?.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800 mb-3">
              ⚠ لم يتم ربط {result.skipped_person_codes.length} كود مندوب بأي موظف:
              <span className="font-mono ms-1">{result.skipped_person_codes.join(', ')}</span>
              <div className="text-xs mt-1">تأكد من تعيين softech_user_id في ملف الموظف.</div>
            </div>
          )}

          {summaries.length === 0 ? (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
              لم يتم العثور على حركات مطابقة للقواعد في هذه الفترة.
              تأكد من صحة كودات الأصناف والمندوبين.
            </div>
          ) : (
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="bg-gray-50 px-4 py-2 border-b grid grid-cols-3 text-xs font-medium text-gray-500">
                <span>المندوب</span>
                <span className="text-center">كود المندوب</span>
                <span className="text-left">إجمالي الحوافز</span>
              </div>
              {summaries.map(s => (
                <div key={s.user_id} className="px-4 py-3 border-b last:border-0 grid grid-cols-3 items-center">
                  <span className="text-sm text-gray-700 font-medium">{s.user_name || `مندوب #${s.user_id}`}</span>
                  <span className="text-xs font-mono text-gray-400 text-center">{s.person_code || '—'}</span>
                  <span className="font-bold text-brand-700 text-left">{fmt(s.total)} ج.م</span>
                </div>
              ))}
              <div className="px-4 py-3 bg-gray-50 grid grid-cols-3 font-bold text-sm">
                <span>الإجمالي</span>
                <span />
                <span className="text-brand-700 text-left">{fmt(summaries.reduce((s, u) => s + Number(u.total || 0), 0))} ج.م</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Report tab — v3: adjustments columns, grand_final
// ─────────────────────────────────────────────────────────────────────────────

function TransactionDrillDown({ programId, userId, periodStart, periodEnd, onClose }) {
  const [rows, setRows]   = useState([])
  const [adjustments, setAdjustments] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    incentivesApi
      .report(programId, { period_start: periodStart, period_end: periodEnd, user_id: userId })
      .then(({ data }) => {
        const found = data.rows?.find(r => r.user_id === userId)
        setRows(found?.transactions || [])
        setAdjustments(data.adjustments || [])
      })
      .finally(() => setLoading(false))
  }, [programId, userId, periodStart, periodEnd])

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 overflow-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl my-8">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="font-bold">تفصيل حركات المندوب</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>
        <div className="overflow-auto max-h-[70vh]">
          {loading ? <Spinner /> : rows.length === 0 ? (
            <EmptyState icon="📋" title="لا توجد حركات" />
          ) : (
            <>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    {['التاريخ', 'رقم الفاتورة', 'الصنف', 'النوع', 'الكمية', 'السعر', 'الحافز', 'حالة'].map(h => (
                      <th key={h} className="px-3 py-2 text-right text-xs text-gray-500 font-medium">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(t => (
                    <tr key={t.id} className={`border-b hover:bg-gray-50 ${t.is_reversed ? 'opacity-50' : ''}`}>
                      <td className="px-3 py-2 text-gray-500 text-xs">{t.erp_date || '—'}</td>
                      <td className="px-3 py-2 font-mono text-xs">{t.doc_no}</td>
                      <td className="px-3 py-2">
                        <div className="font-medium">{t.item_name}</div>
                        <div className="text-xs text-gray-400">{t.item_code}</div>
                      </td>
                      <td className="px-3 py-2">
                        <Badge color={t.doc_type === 'return' ? 'red' : 'blue'}>
                          {t.is_cross_period_return ? '↩ مرتجع خارج فترة' : t.doc_type === 'return' ? 'مرتجع' : 'بيع'}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-right">{fmt(t.quantity, 0)}</td>
                      <td className="px-3 py-2 text-right">{fmt(t.unit_price)}</td>
                      <td className={`px-3 py-2 text-right font-bold ${Number(t.incentive_amount) < 0 ? 'text-red-600' : 'text-green-700'}`}>
                        {fmt(t.incentive_amount)}
                      </td>
                      <td className="px-3 py-2">
                        {t.is_reversed && <Badge color="red">مُعكوس</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {adjustments.length > 0 && (
                <div className="p-4 border-t">
                  <div className="text-sm font-semibold text-gray-600 mb-2">التسويات اليدوية</div>
                  <div className="space-y-1">
                    {adjustments.map(a => (
                      <div key={a.id} className="flex justify-between items-center text-sm bg-orange-50 rounded px-3 py-1.5">
                        <span className="text-gray-700">{a.reason}</span>
                        <span className={`font-bold ${Number(a.amount) < 0 ? 'text-red-600' : 'text-green-700'}`}>
                          {Number(a.amount) > 0 ? '+' : ''}{fmt(a.amount)} ج.م
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function ReportTab({ selectedProgram }) {
  const [form, setForm] = useState({ period_start: monthStart(), period_end: monthEnd() })
  const [rows, setRows]       = useState([])
  const [meta, setMeta]       = useState({})
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState('')
  const [drillUser, setDrillUser] = useState(null)
  const [finalizing, setFinalizing] = useState(false)
  const [finalMsg, setFinalMsg]     = useState('')

  const loadReport = async () => {
    if (!selectedProgram) { setErr('اختر برنامجاً أولاً'); return }
    setLoading(true); setErr(''); setRows([])
    try {
      const { data } = await incentivesApi.report(selectedProgram.id, {
        period_start: form.period_start, period_end: form.period_end,
      })
      setRows(data.rows || [])
      setMeta({
        grand_total:             data.grand_total || 0,
        grand_total_adjustments: data.grand_total_adjustments || 0,
        grand_final:             data.grand_final || 0,
      })
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل تحميل التقرير')
    } finally { setLoading(false) }
  }

  const finalize = async () => {
    if (!window.confirm('هل تريد اعتماد التسويات نهائياً لهذه الفترة؟ لا يمكن التراجع.')) return
    setFinalizing(true); setFinalMsg('')
    try {
      const { data } = await incentivesApi.finalize(selectedProgram.id, {
        period_start: form.period_start, period_end: form.period_end,
      })
      setFinalMsg(`✅ تم الاعتماد: ${data.finalized_count} مندوب / تجاوز: ${data.skipped_count}`)
      loadReport()
    } catch (e) {
      setFinalMsg(e.response?.data?.detail || 'فشل الاعتماد')
    } finally { setFinalizing(false) }
  }

  const hasAdjustments = rows.some(r => Number(r.total_adjustments || 0) !== 0)

  return (
    <div className="space-y-4">
      <h2 className="font-bold text-gray-700">تقرير الحوافز</h2>

      {!selectedProgram && (
        <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
          ⚠ اختر برنامجاً من تبويب البرامج أولاً
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-wrap items-end gap-4">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">من</label>
          <input type="date" className="input" value={form.period_start}
            onChange={e => setForm(f => ({ ...f, period_start: e.target.value }))} />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">إلى</label>
          <input type="date" className="input" value={form.period_end}
            onChange={e => setForm(f => ({ ...f, period_end: e.target.value }))} />
        </div>
        <button className="btn-primary" onClick={loadReport} disabled={loading || !selectedProgram}>
          {loading ? 'جارٍ التحميل...' : '📊 عرض التقرير'}
        </button>
      </div>

      {err && <div className="text-sm text-red-600 bg-red-50 p-3 rounded-lg">{err}</div>}

      {rows.length > 0 && (
        <div>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 border-b flex justify-between items-center flex-wrap gap-2">
              <span className="text-sm font-semibold text-gray-700">
                {rows.length} مندوب — {form.period_start} → {form.period_end}
              </span>
              <div className="flex items-center gap-4 text-sm">
                <span className="text-gray-500">حوافز: <strong className="text-brand-700">{fmt(meta.grand_total)} ج.م</strong></span>
                {hasAdjustments && (
                  <span className="text-gray-500">تسويات: <strong className="text-orange-600">{fmt(meta.grand_total_adjustments)} ج.م</strong></span>
                )}
                <span className="text-gray-500">الصافي: <strong className="text-green-700">{fmt(meta.grand_final)} ج.م</strong></span>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50/50">
                  <tr>
                    {[
                      'المندوب', 'كود المندوب', 'مبيعات', 'مرتجعات',
                      'إجمالي الحوافز',
                      ...(hasAdjustments ? ['التسويات اليدوية', 'الصافي النهائي'] : []),
                      'الحالة', '',
                    ].map(h => (
                      <th key={h} className="px-4 py-2 text-right text-xs text-gray-500 font-medium whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.user_id} className="border-t hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-800">{r.user_name || `#${r.user_id}`}</td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-500">{r.person_code || '—'}</td>
                      <td className="px-4 py-3 text-blue-700">{r.sale_count}</td>
                      <td className="px-4 py-3 text-red-600">{r.return_count}</td>
                      <td className="px-4 py-3 font-bold text-brand-700">{fmt(r.total_incentive)} ج.م</td>
                      {hasAdjustments && (
                        <>
                          <td className={`px-4 py-3 font-medium ${Number(r.total_adjustments || 0) < 0 ? 'text-red-600' : 'text-orange-600'}`}>
                            {Number(r.total_adjustments || 0) !== 0 ? `${Number(r.total_adjustments) > 0 ? '+' : ''}${fmt(r.total_adjustments)} ج.م` : '—'}
                          </td>
                          <td className="px-4 py-3 font-bold text-green-700">{fmt(r.final_total || r.total_incentive)} ج.م</td>
                        </>
                      )}
                      <td className="px-4 py-3">
                        <Badge color={r.is_finalized ? 'green' : 'yellow'}>
                          {r.is_finalized ? 'مُعتمد' : 'مسودة'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <button className="text-xs text-brand-600 hover:text-brand-800 underline"
                          onClick={() => setDrillUser(r.user_id)}>تفصيل</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="px-4 py-3 border-t bg-gray-50 flex items-center justify-between flex-wrap gap-2">
              {finalMsg && <div className="text-sm text-green-700">{finalMsg}</div>}
              <div className="mr-auto">
                <button className="btn-primary text-sm" onClick={finalize}
                  disabled={finalizing || rows.every(r => r.is_finalized)}>
                  {finalizing ? 'جارٍ الاعتماد...' : '✅ اعتماد التسويات نهائياً'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {!loading && rows.length === 0 && !err && (
        <EmptyState icon="📊" title="لا توجد بيانات" sub="شغّل الاحتساب أولاً، ثم اضغط عرض التقرير" />
      )}

      {drillUser && (
        <TransactionDrillDown
          programId={selectedProgram.id}
          userId={drillUser}
          periodStart={form.period_start}
          periodEnd={form.period_end}
          onClose={() => setDrillUser(null)}
        />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Adjustments tab — manual +/- correction entries
// ─────────────────────────────────────────────────────────────────────────────

function AdjustmentForm({ programId, adjustment, staffList, onSaved, onCancel }) {
  const blank = {
    program: programId,
    user: '',
    period_start: monthStart(),
    period_end:   monthEnd(),
    amount: '',
    reason: '',
  }
  const [form, setForm]   = useState(adjustment ? { ...adjustment, user: adjustment.user } : blank)
  const [saving, setSaving] = useState(false)
  const [err, setErr]     = useState('')

  const upd = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.user)   { setErr('اختر المندوب'); return }
    if (!form.amount) { setErr('أدخل المبلغ'); return }
    if (!form.reason.trim()) { setErr('أدخل سبب التسوية'); return }
    setSaving(true); setErr('')
    try {
      const payload = { ...form, program: programId, amount: Number(form.amount) }
      const res = adjustment?.id
        ? await incentivesApi.updateAdjustment(adjustment.id, payload)
        : await incentivesApi.createAdjustment(payload)
      onSaved(res.data)
    } catch (e) {
      setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'حدث خطأ')
    } finally { setSaving(false) }
  }

  return (
    <div className="bg-white border border-orange-200 rounded-xl p-4 space-y-3">
      {err && <div className="text-sm text-red-600 bg-red-50 p-2 rounded">{err}</div>}
      <div>
        <label className="text-xs text-gray-500 mb-1 block">المندوب *</label>
        <select className="input w-full" value={form.user}
          onChange={e => upd('user', e.target.value)}>
          <option value="">— اختر مندوباً —</option>
          {staffList.map(s => (
            <option key={s.id} value={s.id}>
              {s.full_name} {s.person_code ? `(${s.person_code})` : ''}
            </option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">بداية الفترة</label>
          <input type="date" className="input w-full" value={form.period_start}
            onChange={e => upd('period_start', e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">نهاية الفترة</label>
          <input type="date" className="input w-full" value={form.period_end}
            onChange={e => upd('period_end', e.target.value)} />
        </div>
      </div>
      <div>
        <label className="text-xs text-gray-500 mb-1 block">
          المبلغ * <span className="text-gray-400">(موجب = مكافأة، سالب = خصم)</span>
        </label>
        <input type="number" className="input w-full" value={form.amount}
          onChange={e => upd('amount', e.target.value)}
          step="0.01" dir="ltr" placeholder="مثال: 50 أو -20" />
      </div>
      <div>
        <label className="text-xs text-gray-500 mb-1 block">سبب التسوية *</label>
        <textarea className="input w-full" rows={2} value={form.reason}
          onChange={e => upd('reason', e.target.value)}
          placeholder="مثال: تعويض عطل الجهاز، خصم تأخير..." />
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button className="btn-secondary text-sm" onClick={onCancel}>إلغاء</button>
        <button className="btn-primary text-sm" onClick={save} disabled={saving}>
          {saving ? 'جارٍ الحفظ...' : adjustment?.id ? 'حفظ التعديلات' : 'إضافة التسوية'}
        </button>
      </div>
    </div>
  )
}

function AdjustmentsTab({ selectedProgram }) {
  const [adjustments, setAdjustments] = useState([])
  const [staffList, setStaffList]     = useState([])
  const [loading, setLoading]         = useState(false)
  const [addingNew, setAddingNew]     = useState(false)
  const [editingId, setEditingId]     = useState(null)
  const [filterPeriod, setFilterPeriod] = useState({ start: monthStart(), end: monthEnd() })

  const loadStaff = useCallback(async () => {
    try {
      const { data } = await usersApi.list({ page_size: 200 })
      setStaffList(data.results || data)
    } catch { /* ignore */ }
  }, [])

  const load = useCallback(async () => {
    if (!selectedProgram) return
    setLoading(true)
    try {
      const { data } = await incentivesApi.listAdjustments({
        program:      selectedProgram.id,
        period_start: filterPeriod.start,
        period_end:   filterPeriod.end,
      })
      setAdjustments(data.results || data)
    } finally { setLoading(false) }
  }, [selectedProgram, filterPeriod])

  useEffect(() => { loadStaff() }, [loadStaff])
  useEffect(() => { load() },      [load])

  const deleteAdj = async (id) => {
    if (!window.confirm('حذف هذه التسوية؟')) return
    try {
      await incentivesApi.deleteAdjustment(id)
      setAdjustments(prev => prev.filter(a => a.id !== id))
    } catch (e) {
      alert(e.response?.data?.detail || 'فشل الحذف — ربما الفترة مُعتمدة نهائياً')
    }
  }

  if (!selectedProgram) return (
    <EmptyState icon="✏️" title="اختر برنامجاً أولاً" sub="اذهب إلى تبويب البرامج واختر برنامجاً" />
  )

  const grandAdj = adjustments.reduce((s, a) => s + Number(a.amount || 0), 0)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-bold text-gray-700">التسويات اليدوية</h2>
          <div className="text-xs text-gray-500">{selectedProgram.name}</div>
        </div>
        <button className="btn-primary text-sm" onClick={() => { setAddingNew(true); setEditingId(null) }}>
          + تسوية جديدة
        </button>
      </div>

      {addingNew && (
        <div className="mb-2">
          <AdjustmentForm
            programId={selectedProgram.id}
            staffList={staffList}
            onSaved={a => { setAddingNew(false); setAdjustments(prev => [a, ...prev]) }}
            onCancel={() => setAddingNew(false)}
          />
        </div>
      )}

      {/* Period filter */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-wrap items-end gap-4">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">من</label>
          <input type="date" className="input" value={filterPeriod.start}
            onChange={e => setFilterPeriod(f => ({ ...f, start: e.target.value }))} />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">إلى</label>
          <input type="date" className="input" value={filterPeriod.end}
            onChange={e => setFilterPeriod(f => ({ ...f, end: e.target.value }))} />
        </div>
        <RefreshButton loading={loading} onClick={load} size="sm">
          ↻ تحديث
        </RefreshButton>
        {adjustments.length > 0 && (
          <div className="mr-auto text-sm font-semibold">
            الإجمالي:&nbsp;
            <span className={grandAdj < 0 ? 'text-red-600' : 'text-orange-700'}>
              {grandAdj > 0 ? '+' : ''}{fmt(grandAdj)} ج.م
            </span>
          </div>
        )}
      </div>

      {loading ? <Spinner /> : adjustments.length === 0 ? (
        <EmptyState icon="✏️" title="لا توجد تسويات" sub="أضف تسوية يدوية للفترة المحددة" />
      ) : (
        <div className="space-y-2">
          {adjustments.map(a => (
            <div key={a.id}>
              {editingId === a.id ? (
                <AdjustmentForm
                  programId={selectedProgram.id}
                  adjustment={a}
                  staffList={staffList}
                  onSaved={updated => {
                    setAdjustments(prev => prev.map(x => x.id === updated.id ? updated : x))
                    setEditingId(null)
                  }}
                  onCancel={() => setEditingId(null)}
                />
              ) : (
                <div className="bg-white border border-gray-200 rounded-xl p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-gray-800">{a.user_name}</span>
                        <span className="text-xs text-gray-400 font-mono">{a.period_start} → {a.period_end}</span>
                        {a.created_by_name && (
                          <span className="text-xs text-gray-400">بواسطة: {a.created_by_name}</span>
                        )}
                      </div>
                      <div className="text-sm text-gray-600 mt-1">{a.reason}</div>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className={`font-bold text-lg ${Number(a.amount) < 0 ? 'text-red-600' : 'text-green-700'}`}>
                        {Number(a.amount) > 0 ? '+' : ''}{fmt(a.amount)} ج.م
                      </span>
                      <button className="text-xs text-blue-600 hover:text-blue-800"
                        onClick={() => setEditingId(a.id)}>تعديل</button>
                      <button className="text-xs text-red-500 hover:text-red-700"
                        onClick={() => deleteAdj(a.id)}>حذف</button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Settlements tab + Printable Receipt — v3: final_payout, adjustments
// ─────────────────────────────────────────────────────────────────────────────

function ReceiptModal({ settlementId, onClose }) {
  const [data, setData]   = useState(null)
  const [loading, setLoading] = useState(true)
  const printRef = useRef()

  useEffect(() => {
    incentivesApi.receipt(settlementId)
      .then(({ data: d }) => setData(d))
      .finally(() => setLoading(false))
  }, [settlementId])

  const handlePrint = () => {
    const content = printRef.current?.innerHTML
    const win = window.open('', '_blank')
    win.document.write(`
      <!DOCTYPE html><html dir="rtl" lang="ar-u-nu-latn">
      <head>
        <meta charset="UTF-8">
        <title>إيصال حوافز</title>
        <style>
          body { font-family: Arial, sans-serif; padding: 20px; }
          table { width: 100%; border-collapse: collapse; margin-top: 12px; }
          th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: right; }
          th { background: #f3f4f6; font-size: 12px; }
          td { font-size: 13px; }
          .header { border-bottom: 2px solid #333; padding-bottom: 12px; margin-bottom: 12px; }
          .total { font-weight: bold; font-size: 16px; color: #1d4ed8; }
          .final-payout { font-weight: bold; font-size: 18px; color: #15803d; }
          .adj-row { background: #fff7ed; }
        </style>
      </head>
      <body>${content}</body></html>
    `)
    win.document.close()
    win.print()
  }

  const s = data?.settlement

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 overflow-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl my-8">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="font-bold">إيصال تسوية الحوافز</h2>
          <div className="flex gap-2">
            <button className="btn-secondary text-sm" onClick={handlePrint}>🖨 طباعة</button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
          </div>
        </div>

        <div className="p-6" ref={printRef}>
          {loading ? <Spinner /> : !s ? null : (
            <>
              <div className="header mb-4">
                <div className="text-xl font-bold">صيدليات الرزيقي</div>
                <div className="text-sm text-gray-500 mt-1">إيصال تسوية حوافز المبيعات</div>
              </div>
              <div className="grid grid-cols-2 gap-4 mb-4 text-sm">
                <div>
                  <div className="text-gray-500 text-xs">البرنامج</div>
                  <div className="font-semibold">{s.program_name}</div>
                </div>
                <div>
                  <div className="text-gray-500 text-xs">المندوب</div>
                  <div className="font-semibold">{s.user_name}</div>
                </div>
                <div>
                  <div className="text-gray-500 text-xs">الفترة</div>
                  <div className="font-semibold">{s.period_start} → {s.period_end}</div>
                </div>
                <div>
                  <div className="text-gray-500 text-xs">تاريخ الاعتماد</div>
                  <div className="font-semibold">{s.finalized_at?.slice(0, 10) || '—'}</div>
                </div>
              </div>

              {/* Totals summary */}
              <div className="space-y-2 mb-4">
                <div className="bg-brand-50 border border-brand-200 rounded-lg p-3 flex justify-between items-center">
                  <span className="text-sm text-gray-600">إجمالي الحوافز المحتسبة</span>
                  <span className="total">{fmt(s.total_incentive)} ج.م</span>
                </div>
                {Number(s.total_adjustments || 0) !== 0 && (
                  <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 flex justify-between items-center">
                    <span className="text-sm text-gray-600">التسويات اليدوية</span>
                    <span className={`font-bold text-base ${Number(s.total_adjustments) < 0 ? 'text-red-600' : 'text-orange-700'}`}>
                      {Number(s.total_adjustments) > 0 ? '+' : ''}{fmt(s.total_adjustments)} ج.م
                    </span>
                  </div>
                )}
                <div className="bg-green-50 border border-green-300 rounded-lg p-3 flex justify-between items-center">
                  <span className="text-sm font-semibold text-gray-700">الصافي النهائي للصرف</span>
                  <span className="final-payout">{fmt(s.final_payout || s.total_incentive)} ج.م</span>
                </div>
              </div>

              {/* Adjustments detail */}
              {data.adjustments?.length > 0 && (
                <div className="mb-4">
                  <div className="font-semibold text-sm mb-2 text-gray-600">تفصيل التسويات اليدوية</div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr>
                        <th>السبب</th><th>الفترة</th><th>المبلغ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.adjustments.map(a => (
                        <tr key={a.id} className="adj-row">
                          <td>{a.reason}</td>
                          <td className="text-xs text-gray-400">{a.period_start}→{a.period_end}</td>
                          <td className={`text-right font-bold ${Number(a.amount) < 0 ? 'text-red-600' : 'text-green-700'}`}>
                            {Number(a.amount) > 0 ? '+' : ''}{fmt(a.amount)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Item summary */}
              <div className="font-semibold text-sm mb-2">تفصيل الأصناف</div>
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th>الصنف</th>
                    <th>القاعدة</th>
                    <th>مباع</th>
                    <th>مرتجع</th>
                    <th>صافي الكمية</th>
                    <th>الحافز</th>
                  </tr>
                </thead>
                <tbody>
                  {data.item_summary.map(s => (
                    <tr key={s.item_code}>
                      <td>
                        <div className="font-medium">{s.item_name}</div>
                        <div className="text-xs text-gray-400">{s.item_code}</div>
                      </td>
                      <td className="text-gray-500 text-xs">{s.rule_name || '—'}</td>
                      <td className="text-right text-blue-600">{fmt(s.qty_sold || 0, 0)}</td>
                      <td className="text-right text-red-500">{s.qty_returned ? `(${fmt(s.qty_returned, 0)})` : '—'}</td>
                      <td className="text-right">{fmt(s.net_qty, 0)}</td>
                      <td className={`text-right font-bold ${Number(s.total_incentive) < 0 ? 'text-red-600' : 'text-green-700'}`}>
                        {fmt(s.total_incentive)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {s.notes && (
                <div className="mt-4 text-sm text-gray-500 border-t pt-3">
                  ملاحظات: {s.notes}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function SettlementsTab({ selectedProgram }) {
  const [settlements, setSettlements] = useState([])
  const [loading, setLoading]         = useState(false)
  const [receiptId, setReceiptId]     = useState(null)
  const [programFilter, setProgramFilter] = useState(selectedProgram?.id || '')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = { is_finalized: 'true' }
      if (programFilter) params.program = programFilter
      const { data } = await incentivesApi.listSettlements(params)
      setSettlements(data.results || data)
    } finally { setLoading(false) }
  }, [programFilter])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (selectedProgram) setProgramFilter(selectedProgram.id) }, [selectedProgram])

  const grandTotal     = settlements.reduce((s, x) => s + Number(x.total_incentive || 0), 0)
  const grandFinal     = settlements.reduce((s, x) => s + Number(x.final_payout || x.total_incentive || 0), 0)
  const hasAdjustments = settlements.some(x => Number(x.total_adjustments || 0) !== 0)

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-bold text-gray-700">تسويات مُعتمدة</h2>
        <div className="flex items-center gap-2">
          {selectedProgram && settlements.length > 0 && (
            <ExportSettlementsButton
              program={selectedProgram}
              settlements={settlements}
            />
          )}
          <RefreshButton loading={loading} onClick={load} size="sm">↻ تحديث</RefreshButton>
        </div>
      </div>

      {settlements.length > 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-3 mb-4 flex gap-6 text-sm">
          <span>إجمالي الحوافز: <strong className="text-brand-700">{fmt(grandTotal)} ج.م</strong></span>
          {hasAdjustments && (
            <span>بعد التسويات: <strong className="text-green-700">{fmt(grandFinal)} ج.م</strong></span>
          )}
          <span className="text-gray-400">{settlements.length} تسوية</span>
        </div>
      )}

      {loading ? <Spinner /> : settlements.length === 0 ? (
        <EmptyState icon="✅" title="لا توجد تسويات مُعتمدة" sub="اعتمد تقريراً من تبويب التقرير" />
      ) : (
        <div className="space-y-2">
          {settlements.map(s => (
            <div key={s.id} className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-gray-800">{s.user_name}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{s.program_name}</div>
                  <div className="text-xs text-gray-400 mt-1">
                    {s.period_start} → {s.period_end}
                    &nbsp;·&nbsp; {s.transaction_count} حركة
                    &nbsp;·&nbsp; اعتمد: {s.finalized_by_name || '—'} في {s.finalized_at?.slice(0, 10)}
                  </div>
                </div>
                <div className="text-left flex flex-col items-end gap-1">
                  <div className="text-xs text-gray-400">حوافز محتسبة</div>
                  <span className="font-bold text-brand-700 text-base">{fmt(s.total_incentive)} ج.م</span>
                  {Number(s.total_adjustments || 0) !== 0 && (
                    <>
                      <div className="text-xs text-gray-400">بعد التسويات</div>
                      <span className="font-bold text-green-700 text-lg">{fmt(s.final_payout)} ج.م</span>
                    </>
                  )}
                  <button className="btn-secondary text-xs mt-1" onClick={() => setReceiptId(s.id)}>🖨 إيصال</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {receiptId && <ReceiptModal settlementId={receiptId} onClose={() => setReceiptId(null)} />}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// History tab — read-only calculation audit log
// ─────────────────────────────────────────────────────────────────────────────

function HistoryTab({ selectedProgram }) {
  const [logs, setLogs]         = useState([])
  const [loading, setLoading]   = useState(false)
  const [modeFilter, setModeFilter] = useState('')
  const [expandedId, setExpandedId] = useState(null)

  const load = useCallback(async () => {
    if (!selectedProgram) return
    setLoading(true)
    try {
      const params = { program: selectedProgram.id }
      if (modeFilter) params.mode = modeFilter
      const { data } = await incentivesApi.listLogs(params)
      setLogs(data.results || data)
    } finally { setLoading(false) }
  }, [selectedProgram, modeFilter])

  useEffect(() => { load() }, [load])

  if (!selectedProgram) return (
    <EmptyState icon="🕒" title="اختر برنامجاً أولاً" sub="اذهب إلى تبويب البرامج واختر برنامجاً" />
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-bold text-gray-700">سجل عمليات الاحتساب</h2>
          <div className="text-xs text-gray-500">{selectedProgram.name}</div>
        </div>
        <div className="flex items-center gap-2">
          <select className="text-sm border border-gray-200 rounded-lg px-2 py-1.5"
            value={modeFilter} onChange={e => setModeFilter(e.target.value)}>
            <option value="">كل الأنواع</option>
            <option value="calculate">احتساب فعلي</option>
            <option value="simulate">محاكاة</option>
          </select>
          <RefreshButton loading={loading} onClick={load} size="sm">↻ تحديث</RefreshButton>
        </div>
      </div>

      {loading ? <Spinner /> : logs.length === 0 ? (
        <EmptyState icon="🕒" title="لا توجد سجلات" sub="لم يتم تشغيل أي احتساب بعد" />
      ) : (
        <div className="space-y-2">
          {logs.map(log => (
            <div key={log.id} className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div
                className="p-4 cursor-pointer hover:bg-gray-50 flex items-start justify-between gap-4"
                onClick={() => setExpandedId(expandedId === log.id ? null : log.id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge color={log.mode === 'simulate' ? 'purple' : 'blue'}>
                      {log.mode_label || log.mode}
                    </Badge>
                    <Badge color={log.status === 'done' ? 'green' : 'red'}>
                      {log.status_label || log.status}
                    </Badge>
                    <span className="text-sm font-medium text-gray-700">
                      {log.period_start} → {log.period_end}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-400 flex-wrap">
                    <span>📋 {log.transactions_created} حركة</span>
                    {log.triggered_by_name && <span>بواسطة: {log.triggered_by_name}</span>}
                    <span>🕐 {log.started_at?.slice(0, 16)?.replace('T', ' ')}</span>
                    {log.duration_seconds != null && (
                      <span>⏱ {Number(log.duration_seconds).toFixed(1)}ث</span>
                    )}
                  </div>
                </div>
                <span className="text-gray-400 text-sm">{expandedId === log.id ? '▲' : '▼'}</span>
              </div>

              {expandedId === log.id && (
                <div className="border-t bg-gray-50 p-4 space-y-3">
                  {/* Skipped person codes */}
                  {log.skipped_person_codes?.length > 0 && (
                    <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
                      <strong>كودات مندوبين غير مرتبطة ({log.skipped_person_codes.length}):</strong>
                      <span className="font-mono ms-1">{log.skipped_person_codes.join(', ')}</span>
                    </div>
                  )}

                  {/* Error detail */}
                  {log.error_detail && (
                    <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">
                      <strong>خطأ:</strong> {log.error_detail}
                    </div>
                  )}

                  {/* User summaries */}
                  {log.user_summaries && Object.keys(log.user_summaries).length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-gray-600 mb-2">ملخص المندوبين</div>
                      <div className="rounded-xl border border-gray-200 overflow-hidden">
                        <table className="w-full text-xs">
                          <thead className="bg-gray-100">
                            <tr>
                              <th className="px-3 py-1.5 text-right font-medium text-gray-500">المندوب</th>
                              <th className="px-3 py-1.5 text-right font-medium text-gray-500">كود المندوب</th>
                              <th className="px-3 py-1.5 text-right font-medium text-gray-500">الحوافز</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(Array.isArray(log.user_summaries)
                              ? log.user_summaries
                              : Object.entries(log.user_summaries).map(([uid, total]) => ({ user_id: uid, user_name: `#${uid}`, total }))
                            ).sort((a, b) => Number(b.total) - Number(a.total)).map(u => (
                              <tr key={u.user_id} className="border-t">
                                <td className="px-3 py-1.5 font-medium text-gray-700">{u.user_name || `#${u.user_id}`}</td>
                                <td className="px-3 py-1.5 font-mono text-gray-400">{u.person_code || '—'}</td>
                                <td className="px-3 py-1.5 font-bold text-brand-700 text-left">{fmt(u.total)} ج.م</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Near Expiry Tab
// ─────────────────────────────────────────────────────────────────────────────

const BUCKET_COLORS = {
  '0-30':   'bg-red-100 text-red-800 border-red-200',
  '31-60':  'bg-orange-100 text-orange-800 border-orange-200',
  '61-90':  'bg-yellow-100 text-yellow-800 border-yellow-200',
  '91-180': 'bg-blue-100 text-blue-800 border-blue-200',
  '181+':   'bg-gray-100 text-gray-700 border-gray-200',
}
const BUCKET_LABELS = {
  '0-30':   '0–30 يوم (حرج)',
  '31-60':  '31–60 يوم',
  '61-90':  '61–90 يوم',
  '91-180': '91–180 يوم',
  '181+':   'أكثر من 180 يوم',
}

function NearExpiryTab({ selectedProgram }) {
  // ── Stock section (live from SOFTECH stkbalexpiry) ─────────────────────────
  const [stockDays, setStockDays]       = useState('90')
  const [storeCodes, setStoreCodes]     = useState('')
  const [includeQuarantine, setIncludeQuarantine] = useState(false)
  const [stockData, setStockData]       = useState(null)
  const [stockLoading, setStockLoading] = useState(false)
  const [stockErr, setStockErr]         = useState('')

  // ── Report section (from calculated IncentiveTransactions) ────────────────
  const [periodStart, setPeriodStart]   = useState(monthStart())
  const [periodEnd, setPeriodEnd]       = useState(monthEnd())
  const [reportData, setReportData]     = useState(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportErr, setReportErr]       = useState('')

  const loadStock = async () => {
    setStockLoading(true); setStockErr('')
    try {
      const params = { expiry_within_days: Number(stockDays) || 90 }
      if (storeCodes.trim()) params.store_codes = storeCodes.trim()
      if (includeQuarantine) params.include_quarantine = 'true'
      const { data } = await incentivesApi.nearExpiryStock(params)
      setStockData(data)
    } catch (e) {
      setStockErr(e.response?.data?.detail || 'فشل الاستعلام')
    } finally { setStockLoading(false) }
  }

  const loadReport = async () => {
    if (!selectedProgram) { setReportErr('اختر برنامجاً أولاً'); return }
    setReportLoading(true); setReportErr('')
    try {
      const { data } = await incentivesApi.nearExpiryReport(selectedProgram.id, {
        period_start: periodStart,
        period_end:   periodEnd,
      })
      setReportData(data)
    } catch (e) {
      setReportErr(e.response?.data?.detail || 'فشل التقرير')
    } finally { setReportLoading(false) }
  }

  return (
    <div className="space-y-8 max-w-6xl">

      {/* ── Section A: Live Near-Expiry Stock ──────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="bg-orange-50 border-b border-orange-100 px-6 py-4 flex items-center gap-3">
          <span className="text-2xl">⏰</span>
          <div>
            <div className="font-bold text-gray-800">مخزون قريب الصلاحية</div>
            <div className="text-xs text-gray-500">استعلام مباشر من قاعدة بيانات SOFTECH (stkbalexpiry)</div>
          </div>
        </div>
        <div className="p-6">
          <div className="flex flex-wrap gap-3 items-end mb-4">
            <div>
              <label className="text-xs text-gray-500 block mb-1">ينتهي خلال (أيام)</label>
              <input type="number" className="input w-28" dir="ltr"
                value={stockDays} onChange={e => setStockDays(e.target.value)}
                min="1" max="730" step="1" />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">المخازن (اختياري، مفصولة بفاصلة)</label>
              <input className="input w-48" dir="ltr" placeholder="100,110,160"
                value={storeCodes} onChange={e => setStoreCodes(e.target.value)} />
            </div>
            <label className="flex items-center gap-2 cursor-pointer pb-2">
              <input type="checkbox" checked={includeQuarantine}
                onChange={e => setIncludeQuarantine(e.target.checked)} />
              <span className="text-xs text-gray-600">تضمين مخازن الحجر/التالف</span>
            </label>
            <button className="btn-primary" onClick={loadStock} disabled={stockLoading}>
              {stockLoading ? 'جارٍ الاستعلام...' : 'استعلام'}
            </button>
          </div>
          {!includeQuarantine && (
            <div className="text-xs text-gray-400 mb-3">
              * مخازن الحجر/التالف (102، 103، 105) مستبعدة افتراضياً — المخزون فيها غير قابل للبيع
            </div>
          )}

          {stockErr && (
            <div className="text-sm text-red-600 bg-red-50 p-3 rounded-lg mb-4">{stockErr}</div>
          )}

          {stockData && (
            <div className="space-y-5">
              {/* Summary cards */}
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-gray-50 rounded-xl p-4 text-center">
                  <div className="text-2xl font-bold text-gray-800">{stockData.total_items}</div>
                  <div className="text-xs text-gray-500 mt-1">صنف متأثر</div>
                </div>
                <div className="bg-gray-50 rounded-xl p-4 text-center">
                  <div className="text-2xl font-bold text-gray-800">{stockData.total_batches}</div>
                  <div className="text-xs text-gray-500 mt-1">دُفعة</div>
                </div>
                <div className="bg-gray-50 rounded-xl p-4 text-center">
                  <div className="text-2xl font-bold text-gray-800">{fmt(stockData.total_qty, 0)}</div>
                  <div className="text-xs text-gray-500 mt-1">إجمالي الكمية</div>
                </div>
              </div>

              {/* Bucket breakdown */}
              <div>
                <div className="text-sm font-semibold text-gray-700 mb-3">توزيع الأيام المتبقية</div>
                <div className="flex flex-wrap gap-2">
                  {stockData.summary_by_bucket?.map(b => (
                    <div key={b.bucket}
                      className={`rounded-xl border px-4 py-3 text-center min-w-[110px] ${BUCKET_COLORS[b.bucket] || 'bg-gray-50'}`}>
                      <div className="text-lg font-bold">{b.count}</div>
                      <div className="text-xs opacity-75 mt-0.5">{BUCKET_LABELS[b.bucket]}</div>
                      <div className="text-xs opacity-60">{fmt(b.qty, 0)} وحدة</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Store summary */}
              {stockData.summary_by_store?.length > 0 && (
                <div>
                  <div className="text-sm font-semibold text-gray-700 mb-2">توزيع المخازن</div>
                  <div className="flex flex-wrap gap-2">
                    {stockData.summary_by_store.map(s => (
                      <div key={s.store_code} className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 text-xs">
                        <span className="font-mono font-semibold text-blue-700">{s.store_code}</span>
                        <span className="text-gray-600 ms-2">{fmt(s.total_qty, 0)} وحدة</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Items table */}
              {stockData.items?.length > 0 && (
                <div>
                  <div className="text-sm font-semibold text-gray-700 mb-2">
                    الأصناف ({stockData.items.length})
                  </div>
                  <div className="rounded-xl border border-gray-200 overflow-hidden">
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="px-3 py-2 text-right font-medium text-gray-500">الصنف</th>
                            <th className="px-3 py-2 text-right font-medium text-gray-500">الكود</th>
                            <th className="px-3 py-2 text-right font-medium text-gray-500">الكمية</th>
                            <th className="px-3 py-2 text-right font-medium text-gray-500">رقم الدُفعة</th>
                            <th className="px-3 py-2 text-right font-medium text-gray-500">تاريخ الصلاحية</th>
                            <th className="px-3 py-2 text-right font-medium text-gray-500">الأيام المتبقية</th>
                            <th className="px-3 py-2 text-right font-medium text-gray-500">المخزن</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {stockData.items.map((item, idx) => (
                            <tr key={idx} className="hover:bg-gray-50">
                              <td className="px-3 py-2">{item.item_name}</td>
                              <td className="px-3 py-2 font-mono text-gray-500">{item.itemcode}</td>
                              <td className="px-3 py-2 font-semibold">{fmt(item.itemqty, 2)}</td>
                              <td className="px-3 py-2 font-mono text-gray-500">{item.batchno || '—'}</td>
                              <td className="px-3 py-2">{item.itemexpirydate?.slice(0, 10) || '—'}</td>
                              <td className="px-3 py-2">
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border
                                  ${BUCKET_COLORS[item.expiry_bucket] || 'bg-gray-100 text-gray-600'}`}>
                                  {item.days_remaining} يوم
                                </span>
                              </td>
                              <td className="px-3 py-2 font-mono text-gray-500">
                                {item.storecode}
                                {item.is_quarantine && (
                                  <span className="ms-1 text-orange-500" title="مخزن حجر/تالف">⚠</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {stockData.items?.length === 0 && (
                <EmptyState icon="✅" title="لا توجد أصناف قريبة الصلاحية"
                  sub={`لا يوجد مخزون ينتهي خلال ${stockDays} يوماً`} />
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Section B: Near-Expiry Incentive Report ─────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="bg-blue-50 border-b border-blue-100 px-6 py-4 flex items-center gap-3">
          <span className="text-2xl">📊</span>
          <div>
            <div className="font-bold text-gray-800">تقرير حوافز قريبة الصلاحية</div>
            <div className="text-xs text-gray-500">
              {selectedProgram
                ? `البرنامج: ${selectedProgram.name}`
                : 'اختر برنامجاً من تبويب البرامج أولاً'}
            </div>
          </div>
        </div>
        <div className="p-6">
          <div className="flex flex-wrap gap-3 items-end mb-4">
            <div>
              <label className="text-xs text-gray-500 block mb-1">من تاريخ</label>
              <input type="date" className="input" value={periodStart}
                onChange={e => setPeriodStart(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">إلى تاريخ</label>
              <input type="date" className="input" value={periodEnd}
                onChange={e => setPeriodEnd(e.target.value)} />
            </div>
            <button className="btn-primary" onClick={loadReport}
              disabled={reportLoading || !selectedProgram}>
              {reportLoading ? 'جارٍ التحميل...' : 'عرض التقرير'}
            </button>
          </div>

          {!selectedProgram && (
            <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
              اختر برنامج حوافز من تبويب "البرامج" ثم عد إلى هذا التبويب.
            </div>
          )}

          {reportErr && (
            <div className="text-sm text-red-600 bg-red-50 p-3 rounded-lg">{reportErr}</div>
          )}

          {reportData && (
            <div className="space-y-6">
              {/* Grand totals */}
              {reportData.grand_totals && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    { label: 'إجمالي الحوافز', val: fmt(reportData.grand_totals.total_incentive) + ' ج.م', color: 'text-green-700' },
                    { label: 'وحدات مُباعة', val: fmt(reportData.grand_totals.qty_sold, 0), color: 'text-blue-700' },
                    { label: 'وحدات مُرتجعة', val: fmt(reportData.grand_totals.qty_returned, 0), color: 'text-red-700' },
                    { label: 'فواتير بيع', val: reportData.grand_totals.sale_count, color: 'text-gray-800' },
                  ].map(c => (
                    <div key={c.label} className="bg-gray-50 rounded-xl p-4 text-center">
                      <div className={`text-xl font-bold ${c.color}`}>{c.val}</div>
                      <div className="text-xs text-gray-500 mt-1">{c.label}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Bucket breakdown */}
              {reportData.expiry_bucket_breakdown?.length > 0 && (
                <div>
                  <div className="text-sm font-semibold text-gray-700 mb-3">توزيع الحوافز حسب الأيام المتبقية</div>
                  <div className="flex flex-wrap gap-2">
                    {reportData.expiry_bucket_breakdown.map(b => (
                      b.sale_count > 0 && (
                        <div key={b.bucket}
                          className={`rounded-xl border px-4 py-3 min-w-[130px] text-center ${BUCKET_COLORS[b.bucket] || 'bg-gray-50'}`}>
                          <div className="text-base font-bold">{fmt(b.incentive)} ج.م</div>
                          <div className="text-xs opacity-75 mt-0.5">{BUCKET_LABELS[b.bucket]}</div>
                          <div className="text-xs opacity-60">{b.sale_count} فاتورة • {fmt(b.qty_sold, 0)} وحدة</div>
                        </div>
                      )
                    ))}
                  </div>
                </div>
              )}

              {/* Employee ranking */}
              {reportData.employee_ranking?.length > 0 && (
                <div>
                  <div className="text-sm font-semibold text-gray-700 mb-2">ترتيب المندوبين</div>
                  <div className="rounded-xl border border-gray-200 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-2 text-right font-medium text-gray-500">#</th>
                          <th className="px-4 py-2 text-right font-medium text-gray-500">المندوب</th>
                          <th className="px-4 py-2 text-right font-medium text-gray-500">كود المندوب</th>
                          <th className="px-4 py-2 text-right font-medium text-gray-500">إجمالي الحوافز</th>
                          <th className="px-4 py-2 text-right font-medium text-gray-500">الحركات</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {reportData.employee_ranking.map((e, i) => (
                          <tr key={e.user_id} className="hover:bg-gray-50">
                            <td className="px-4 py-2 text-gray-400">{i + 1}</td>
                            <td className="px-4 py-2 font-medium">{e.user_name}</td>
                            <td className="px-4 py-2 font-mono text-gray-500 text-xs">{e.person_code}</td>
                            <td className="px-4 py-2 font-bold text-green-700">{fmt(e.total)} ج.م</td>
                            <td className="px-4 py-2 text-gray-500">{e.txn_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Item ranking */}
              {reportData.item_ranking?.length > 0 && (
                <div>
                  <div className="text-sm font-semibold text-gray-700 mb-2">
                    الأصناف الأكثر بيعاً (قريبة الصلاحية)
                  </div>
                  <div className="rounded-xl border border-gray-200 overflow-hidden">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-3 py-2 text-right font-medium text-gray-500">#</th>
                          <th className="px-3 py-2 text-right font-medium text-gray-500">الصنف</th>
                          <th className="px-3 py-2 text-right font-medium text-gray-500">الكمية المُباعة</th>
                          <th className="px-3 py-2 text-right font-medium text-gray-500">إجمالي الحوافز</th>
                          <th className="px-3 py-2 text-right font-medium text-gray-500">متوسط أيام الصلاحية</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {reportData.item_ranking.map((it, i) => (
                          <tr key={it.item_code} className="hover:bg-gray-50">
                            <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                            <td className="px-3 py-2">
                              <div className="font-medium">{it.item_name}</div>
                              <div className="text-gray-400 font-mono text-xs">{it.item_code}</div>
                            </td>
                            <td className="px-3 py-2">{fmt(it.qty_sold, 0)}</td>
                            <td className="px-3 py-2 font-bold text-green-700">{fmt(it.total_incentive)} ج.م</td>
                            <td className="px-3 py-2">
                              <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-xs
                                ${it.avg_expiry_days <= 30 ? BUCKET_COLORS['0-30'] :
                                  it.avg_expiry_days <= 60 ? BUCKET_COLORS['31-60'] :
                                  it.avg_expiry_days <= 90 ? BUCKET_COLORS['61-90'] :
                                  BUCKET_COLORS['91-180']}`}>
                                {it.avg_expiry_days} يوم
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {reportData.note && (
                <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
                  {reportData.note}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Excel Export Button  (Feature 6)
// ─────────────────────────────────────────────────────────────────────────────

function ExportSettlementsButton({ program, settlements }) {
  const [exporting, setExporting] = useState(false)

  // Infer period from settlements
  const periodStart = settlements[0]?.period_start
  const periodEnd   = settlements[0]?.period_end

  const doExport = async () => {
    if (!periodStart || !periodEnd) return
    setExporting(true)
    try {
      const { data } = await incentivesApi.exportSettlements(program.id, {
        period_start: periodStart,
        period_end:   periodEnd,
      })
      const url  = window.URL.createObjectURL(new Blob([data]))
      const link = document.createElement('a')
      link.href  = url
      link.setAttribute('download', `incentives_${program.id}_${periodStart}.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      alert('فشل التصدير: ' + (e.message || 'خطأ غير معروف'))
    } finally { setExporting(false) }
  }

  return (
    <button
      className="text-sm btn-secondary flex items-center gap-1"
      onClick={doExport}
      disabled={exporting}
    >
      <span>📥</span>
      {exporting ? 'جارٍ التصدير...' : 'تصدير Excel'}
    </button>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// ROI Tab  (Feature 10)
// ─────────────────────────────────────────────────────────────────────────────

function ROITab({ selectedProgram }) {
  const [periodStart, setPeriodStart] = useState(monthStart())
  const [periodEnd, setPeriodEnd]     = useState(monthEnd())
  const [compDays, setCompDays]       = useState('30')
  const [data, setData]               = useState(null)
  const [loading, setLoading]         = useState(false)
  const [err, setErr]                 = useState('')

  const load = async () => {
    if (!selectedProgram) { setErr('اختر برنامجاً أولاً'); return }
    setLoading(true); setErr('')
    try {
      const { data: res } = await incentivesApi.roiReport(selectedProgram.id, {
        period_start:    periodStart,
        period_end:      periodEnd,
        comparison_days: Number(compDays) || 30,
      })
      setData(res)
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل تحميل التقرير')
    } finally { setLoading(false) }
  }

  const roi = data?.financials?.roi_multiple
  const roiColor = roi == null ? 'text-gray-500' :
                   roi >= 3   ? 'text-green-600' :
                   roi >= 1   ? 'text-yellow-600' : 'text-red-500'

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
        <h2 className="font-bold text-gray-800 mb-4 flex items-center gap-2">
          <span>📈</span> تقرير عائد الاستثمار (ROI)
        </h2>
        {!selectedProgram && (
          <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
            اختر برنامجاً من تبويب البرامج أولاً
          </div>
        )}
        <div className="flex flex-wrap gap-3 items-end mb-4">
          <div>
            <label className="text-xs text-gray-500 block mb-1">من تاريخ</label>
            <input type="date" className="input" value={periodStart}
              onChange={e => setPeriodStart(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">إلى تاريخ</label>
            <input type="date" className="input" value={periodEnd}
              onChange={e => setPeriodEnd(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">نافذة المقارنة (أيام)</label>
            <input type="number" className="input w-24" dir="ltr"
              value={compDays} onChange={e => setCompDays(e.target.value)}
              min="7" max="90" />
          </div>
          <button className="btn-primary" onClick={load}
            disabled={loading || !selectedProgram}>
            {loading ? 'جارٍ الحساب...' : 'احسب ROI'}
          </button>
        </div>
        {err && <div className="text-sm text-red-600 bg-red-50 p-3 rounded-lg">{err}</div>}
      </div>

      {data && (
        <div className="space-y-5">
          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-white rounded-xl border p-4 text-center">
              <div className="text-xs text-gray-500 mb-1">تكلفة الحوافز</div>
              <div className="text-2xl font-bold text-red-600">{fmt(data.financials.incentive_cost)} ج.م</div>
            </div>
            <div className="bg-white rounded-xl border p-4 text-center">
              <div className="text-xs text-gray-500 mb-1">الإيرادات الإضافية</div>
              <div className={`text-2xl font-bold ${data.financials.revenue_uplift > 0 ? 'text-green-600' : 'text-red-600'}`}>
                {fmt(data.financials.revenue_uplift)} ج.م
              </div>
            </div>
            <div className="bg-white rounded-xl border p-4 text-center col-span-2">
              <div className="text-xs text-gray-500 mb-1">معامل ROI</div>
              <div className={`text-4xl font-bold ${roiColor}`}>
                {roi !== null ? `${roi}×` : '—'}
              </div>
              {roi !== null && (
                <div className="text-xs mt-1 text-gray-400">
                  {roi >= 3 ? 'ممتاز' : roi >= 1 ? 'مقبول' : 'أقل من التعادل'}
                </div>
              )}
            </div>
          </div>

          {/* Velocity comparison */}
          <div className="bg-white rounded-xl border p-5">
            <div className="text-sm font-semibold text-gray-700 mb-4">معدل المبيعات اليومي (وحدة/يوم)</div>
            <div className="grid grid-cols-3 gap-4 text-center">
              <div className="bg-gray-50 rounded-xl p-4">
                <div className="text-xs text-gray-500 mb-1">قبل البرنامج</div>
                <div className="text-2xl font-bold text-gray-700">{fmt(data.velocity.before_daily_qty, 1)}</div>
              </div>
              <div className="bg-brand-50 rounded-xl p-4 border border-brand-200">
                <div className="text-xs text-brand-500 mb-1">خلال البرنامج</div>
                <div className="text-2xl font-bold text-brand-700">{fmt(data.velocity.during_daily_qty, 1)}</div>
              </div>
              <div className="bg-gray-50 rounded-xl p-4">
                <div className="text-xs text-gray-500 mb-1">بعد البرنامج</div>
                <div className="text-2xl font-bold text-gray-700">{fmt(data.velocity.after_daily_qty, 1)}</div>
              </div>
            </div>
            <div className="mt-3 text-center text-sm font-semibold">
              <span className={data.velocity.uplift_vs_before > 0 ? 'text-green-600' : 'text-red-500'}>
                {data.velocity.uplift_vs_before > 0 ? '▲' : '▼'}
                {Math.abs(data.velocity.uplift_vs_before)} وحدة/يوم زيادة خلال البرنامج
              </span>
            </div>
          </div>

          {/* Item breakdown */}
          {data.item_breakdown?.length > 0 && (
            <div className="bg-white rounded-xl border overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100 font-semibold text-sm text-gray-700">
                تفاصيل الأصناف
              </div>
              <table className="w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">الصنف</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">قبل</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">خلال</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">بعد</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">الزيادة</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-500">الإيراد</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.item_breakdown.map(it => (
                    <tr key={it.item_code} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-mono text-gray-500">{it.item_code}</td>
                      <td className="px-4 py-2">{it.before_daily_qty}</td>
                      <td className="px-4 py-2 font-semibold text-brand-700">{it.during_daily_qty}</td>
                      <td className="px-4 py-2">{it.after_daily_qty}</td>
                      <td className={`px-4 py-2 font-semibold ${it.velocity_uplift > 0 ? 'text-green-600' : 'text-red-500'}`}>
                        {it.velocity_uplift > 0 ? '+' : ''}{it.velocity_uplift}
                      </td>
                      <td className="px-4 py-2">{fmt(it.during_revenue)} ج.م</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Suggestions Tab  (Feature 3)
// ─────────────────────────────────────────────────────────────────────────────

const TAG_LABELS = {
  near_expiry:  { label: 'قريب الصلاحية', color: 'bg-red-100 text-red-700 border-red-200' },
  slow_moving:  { label: 'بطيء الحركة',   color: 'bg-orange-100 text-orange-700 border-orange-200' },
  high_margin:  { label: 'هامش عالي',     color: 'bg-green-100 text-green-700 border-green-200' },
}

function SuggestionsTab({ selectedProgram }) {
  const [expiryDays, setExpiryDays] = useState('90')
  const [branchCode, setBranchCode] = useState('')
  const [data, setData]             = useState(null)
  const [loading, setLoading]       = useState(false)
  const [err, setErr]               = useState('')
  const [selected, setSelected]     = useState(new Set())
  // Add-to-rule state
  const [rules, setRules]           = useState([])
  const [targetRuleId, setTargetRuleId] = useState('')
  const [adding, setAdding]         = useState(false)
  const [addMsg, setAddMsg]         = useState('')

  // Load the selected program's rules (so suggestions can be added to one)
  useEffect(() => {
    if (!selectedProgram) { setRules([]); setTargetRuleId(''); return }
    incentivesApi.listRules({ program: selectedProgram.id })
      .then(({ data: r }) => {
        const list = r.results || r
        setRules(list)
        if (list.length) setTargetRuleId(String(list[0].id))
      })
      .catch(() => setRules([]))
  }, [selectedProgram])

  const load = async () => {
    setLoading(true); setErr('')
    try {
      const params = { expiry_within_days: Number(expiryDays) || 90, max_results: 50 }
      if (branchCode.trim()) params.branch_code = branchCode.trim()
      const { data: res } = await incentivesApi.suggestItems(params)
      setData(res)
      setSelected(new Set())
      setAddMsg('')
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل الاستعلام')
    } finally { setLoading(false) }
  }

  const toggleAll = () => {
    if (selected.size === data?.items?.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(data.items.map(i => i.item_code)))
    }
  }

  const addSelectedToRule = async () => {
    if (!targetRuleId || selected.size === 0) return
    setAdding(true); setAddMsg('')
    try {
      const items = data.items
        .filter(i => selected.has(i.item_code))
        .map(i => ({ item_code: i.item_code, item_name: i.item_name }))
      const { data: res } = await incentivesApi.importRuleItems(targetRuleId, {
        items, mode: 'append',
      })
      setAddMsg(`تمت إضافة ${res.created} صنف (${res.updated} محدّث) — الإجمالي ${res.total}`)
      setSelected(new Set())
    } catch (e) {
      setAddMsg('فشل: ' + (e.response?.data?.detail || 'خطأ غير معروف'))
    } finally { setAdding(false) }
  }

  return (
    <div className="space-y-5 max-w-5xl">
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-5">
        <h2 className="font-bold text-gray-800 mb-3 flex items-center gap-2">
          <span>🧠</span> اقتراحات ذكية للأصناف
          <span className="text-xs text-gray-400 font-normal">— أصناف مرشحة لبرامج الحوافز</span>
        </h2>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">الصلاحية (أيام)</label>
            <input type="number" className="input w-24" dir="ltr"
              value={expiryDays} onChange={e => setExpiryDays(e.target.value)}
              min="7" max="365" />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">الفرع (اختياري)</label>
            <input className="input w-32" dir="ltr"
              value={branchCode} onChange={e => setBranchCode(e.target.value)}
              placeholder="100" />
          </div>
          <button className="btn-primary" onClick={load} disabled={loading}>
            {loading ? 'جارٍ التحليل...' : 'تحليل وعرض'}
          </button>
        </div>
        {err && <div className="mt-3 text-sm text-red-600 bg-red-50 p-2 rounded">{err}</div>}
      </div>

      {data && (
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
            <span className="font-semibold text-gray-700">{data.count} صنف مرشح</span>
            {selected.size > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-brand-600 font-semibold bg-brand-50 px-3 py-1 rounded-full">
                  {selected.size} محدد
                </span>
                {!selectedProgram ? (
                  <span className="text-xs text-amber-600">اختر برنامجاً لإضافة الأصناف لقاعدة</span>
                ) : rules.length === 0 ? (
                  <span className="text-xs text-amber-600">لا توجد قواعد في البرنامج — أنشئ قاعدة أولاً</span>
                ) : (
                  <>
                    <select className="input text-xs py-1"
                      value={targetRuleId}
                      onChange={e => setTargetRuleId(e.target.value)}>
                      {rules.map(r => (
                        <option key={r.id} value={r.id}>
                          {r.rule_name || r.item_name || `قاعدة #${r.id}`}
                        </option>
                      ))}
                    </select>
                    <button className="btn-primary text-xs py-1"
                      onClick={addSelectedToRule} disabled={adding}>
                      {adding ? 'جارٍ الإضافة...' : `إضافة ${selected.size} للقاعدة`}
                    </button>
                  </>
                )}
              </div>
            )}
            {addMsg && (
              <span className="text-xs text-green-700 bg-green-50 px-3 py-1 rounded-full w-full md:w-auto">
                {addMsg}
              </span>
            )}
          </div>

          {data.items.length === 0 ? (
            <div className="p-12 text-center text-gray-400">
              لا توجد اقتراحات بالمعايير الحالية
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2">
                      <input type="checkbox"
                        checked={selected.size === data.items.length && data.items.length > 0}
                        onChange={toggleAll} />
                    </th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">الصنف</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">السبب</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">الصلاحية</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">الكمية قريبة الصلاحية</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">الحركة الشهرية</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">الهامش %</th>
                    <th className="px-3 py-2 text-right font-medium text-gray-500">السعر</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.items.map(item => (
                    <tr key={item.item_code}
                      className={`hover:bg-gray-50 ${selected.has(item.item_code) ? 'bg-brand-50' : ''}`}
                      onClick={() => setSelected(s => {
                        const next = new Set(s)
                        next.has(item.item_code) ? next.delete(item.item_code) : next.add(item.item_code)
                        return next
                      })}
                    >
                      <td className="px-3 py-2 text-center" onClick={e => e.stopPropagation()}>
                        <input type="checkbox"
                          checked={selected.has(item.item_code)}
                          onChange={() => {
                            setSelected(s => {
                              const next = new Set(s)
                              next.has(item.item_code) ? next.delete(item.item_code) : next.add(item.item_code)
                              return next
                            })
                          }} />
                      </td>
                      <td className="px-3 py-2">
                        <div className="font-medium text-gray-800 max-w-[200px] break-words">{item.item_name}</div>
                        <div className="font-mono text-gray-400">{item.item_code}</div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          {item.tags.map(tag => {
                            const t = TAG_LABELS[tag] || { label: tag, color: 'bg-gray-100 text-gray-600' }
                            return (
                              <span key={tag}
                                className={`px-1.5 py-0.5 rounded-full text-xs border ${t.color}`}>
                                {t.label}
                              </span>
                            )
                          })}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        {item.expiry_days != null
                          ? <span className={`font-semibold ${item.expiry_days <= 30 ? 'text-red-600' : item.expiry_days <= 90 ? 'text-orange-500' : 'text-gray-600'}`}>
                              {item.expiry_days} يوم
                            </span>
                          : '—'}
                      </td>
                      <td className="px-3 py-2">{item.expiry_qty != null ? fmt(item.expiry_qty, 0) : '—'}</td>
                      <td className="px-3 py-2">{item.monthly_avg != null ? fmt(item.monthly_avg, 1) : '—'}</td>
                      <td className="px-3 py-2">{item.margin_pct != null ? `${item.margin_pct}%` : '—'}</td>
                      <td className="px-3 py-2">{item.pack_price != null ? `${fmt(item.pack_price, 0)} ج.م` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Root page component
// ─────────────────────────────────────────────────────────────────────────────

export default function IncentivesPage() {
  const [activeTab, setActiveTab]             = useState('programs')
  const [selectedProgram, setSelectedProgram] = useState(null)

  const handleSelectProgram = (p) => {
    setSelectedProgram(p)
    setActiveTab('rules')
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-gray-50" dir="rtl">
      {/* Page header */}
      <div className="bg-white border-b px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-800">محرك الحوافز</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              برامج الحوافز المبنية على المبيعات الفعلية من SOFTECH
            </p>
          </div>
          {selectedProgram && (
            <div className="flex items-center gap-2 text-sm bg-brand-50 border border-brand-200 px-3 py-1.5 rounded-lg">
              <span className="text-gray-500">البرنامج:</span>
              <span className="font-semibold text-brand-700">{selectedProgram.name}</span>
              <button className="text-gray-400 hover:text-gray-600 mr-1"
                onClick={() => setSelectedProgram(null)}>✕</button>
            </div>
          )}
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 mt-4 border-b -mb-4 overflow-x-auto">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                activeTab === t.id
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}>
              {t.icon} {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'programs'    && <ProgramsTab    selectedProgram={selectedProgram} onSelect={handleSelectProgram} />}
        {activeTab === 'rules'       && <RulesTab       selectedProgram={selectedProgram} />}
        {activeTab === 'calculate'   && <CalculateTab   selectedProgram={selectedProgram} />}
        {activeTab === 'report'      && <ReportTab      selectedProgram={selectedProgram} />}
        {activeTab === 'near-expiry' && <NearExpiryTab   selectedProgram={selectedProgram} />}
        {activeTab === 'roi'         && <ROITab          selectedProgram={selectedProgram} />}
        {activeTab === 'suggestions' && <SuggestionsTab  selectedProgram={selectedProgram} />}
        {activeTab === 'adjustments' && <AdjustmentsTab  selectedProgram={selectedProgram} />}
        {activeTab === 'settlements' && <SettlementsTab selectedProgram={selectedProgram} />}
        {activeTab === 'history'     && <HistoryTab     selectedProgram={selectedProgram} />}
      </div>
    </div>
  )
}
