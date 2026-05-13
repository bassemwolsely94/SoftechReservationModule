/**
 * IncentivesPage.jsx
 *
 * Item-based sales incentive engine UI.
 *
 * Tabs:
 *   1. Programs  — list + create incentive programs
 *   2. Rules     — view / add / edit rules for selected program
 *   3. Calculate — pick period → run engine → preview report
 *   4. Report    — per-user aggregated table with drill-down
 *   5. Settlements — finalized payroll records with printable receipts
 */
import { useState, useCallback, useEffect, useRef } from 'react'
import { incentivesApi } from '../api/client'

// ── Tiny helpers ─────────────────────────────────────────────────────────────

const fmt = (n, dp = 2) =>
  Number(n || 0).toLocaleString('ar-EG', {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })

const today = () => new Date().toISOString().slice(0, 10)

const monthStart = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

const monthEnd = () => {
  const d = new Date()
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0)
  return last.toISOString().slice(0, 10)
}

function Badge({ color = 'gray', children }) {
  const palette = {
    green:  'bg-green-100 text-green-800',
    red:    'bg-red-100 text-red-800',
    blue:   'bg-blue-100 text-blue-800',
    yellow: 'bg-yellow-100 text-yellow-800',
    gray:   'bg-gray-100 text-gray-700',
    purple: 'bg-purple-100 text-purple-800',
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
  { id: 'programs',     label: 'البرامج',       icon: '🏆' },
  { id: 'rules',        label: 'القواعد',        icon: '📐' },
  { id: 'calculate',   label: 'الاحتساب',       icon: '⚡' },
  { id: 'report',       label: 'التقرير',        icon: '📊' },
  { id: 'settlements',  label: 'التسويات',       icon: '✅' },
]

// ─────────────────────────────────────────────────────────────────────────────
// Programs tab
// ─────────────────────────────────────────────────────────────────────────────

function CreateProgramModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    name: '',
    description: '',
    start_date: monthStart(),
    end_date: monthEnd(),
    calculation_period: 'monthly',
    is_active: true,
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
    } finally {
      setSaving(false)
    }
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
  const [programs, setPrograms] = useState([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await incentivesApi.listPrograms()
      setPrograms(data.results || data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-bold text-gray-700">برامج الحوافز</h2>
        <button className="btn-primary text-sm" onClick={() => setShowCreate(true)}>
          + برنامج جديد
        </button>
      </div>

      {loading ? <Spinner /> : programs.length === 0 ? (
        <EmptyState icon="🏆" title="لا توجد برامج حوافز" sub="أنشئ برنامجاً جديداً للبدء" />
      ) : (
        <div className="space-y-3">
          {programs.map(p => (
            <div
              key={p.id}
              onClick={() => onSelect(p)}
              className={`rounded-xl border p-4 cursor-pointer transition-all ${
                selectedProgram?.id === p.id
                  ? 'border-brand-500 bg-brand-50 shadow-sm'
                  : 'border-gray-200 bg-white hover:border-brand-300 hover:shadow-sm'
              }`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold text-gray-800">{p.name}</div>
                  {p.description && (
                    <div className="text-xs text-gray-500 mt-0.5">{p.description}</div>
                  )}
                  <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                    <span>📅 {p.start_date} → {p.end_date}</span>
                    <span>·</span>
                    <span>📐 {p.rule_count} قاعدة</span>
                    <span>·</span>
                    <span className="capitalize">{p.calculation_period}</span>
                  </div>
                </div>
                <Badge color={p.is_active ? 'green' : 'gray'}>
                  {p.is_active ? 'نشط' : 'موقف'}
                </Badge>
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
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Rules tab
// ─────────────────────────────────────────────────────────────────────────────

function RuleForm({ programId, rule, onSaved, onCancel }) {
  const blank = {
    program: programId,
    rule_name: '',
    item_code: '',
    item_name: '',
    category_code: '',
    incentive_type: 'percent',
    incentive_value: '',
    min_qty: '0',
    person_code_filter: '',
    expiry_within_days: '',
    priority: '0',
    is_active: true,
  }
  const [form, setForm] = useState(rule ? { ...rule } : blank)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const upd = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const save = async () => {
    if (!form.incentive_value) { setErr('قيمة الحافز مطلوبة'); return }
    if (!form.item_code && !form.category_code) {
      setErr('يجب تحديد كود الصنف أو كود الفئة'); return
    }
    setSaving(true); setErr('')
    try {
      const payload = {
        ...form,
        program: programId,
        incentive_value: Number(form.incentive_value),
        min_qty: Number(form.min_qty || 0),
        priority: Number(form.priority || 0),
        expiry_within_days: form.expiry_within_days ? Number(form.expiry_within_days) : null,
      }
      let res
      if (rule?.id) {
        res = await incentivesApi.updateRule(rule.id, payload)
      } else {
        res = await incentivesApi.createRule(payload)
      }
      onSaved(res.data)
    } catch (e) {
      setErr(e.response?.data?.detail || JSON.stringify(e.response?.data) || 'حدث خطأ')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white border border-brand-200 rounded-xl p-4 space-y-3">
      {err && <div className="text-sm text-red-600 bg-red-50 p-2 rounded">{err}</div>}

      <div>
        <label className="text-xs text-gray-500 mb-1 block">اسم القاعدة (للعرض)</label>
        <input className="input w-full" value={form.rule_name}
          onChange={e => upd('rule_name', e.target.value)} placeholder="مثال: عروض رمضان" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">كود الصنف</label>
          <input className="input w-full" value={form.item_code}
            onChange={e => upd('item_code', e.target.value)} placeholder="1234" dir="ltr" />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">اسم الصنف (للعرض)</label>
          <input className="input w-full" value={form.item_name}
            onChange={e => upd('item_name', e.target.value)} placeholder="أوجمنتين 625" />
        </div>
      </div>

      <div>
        <label className="text-xs text-gray-500 mb-1 block">كود الفئة (groupcode)</label>
        <input className="input w-full" value={form.category_code}
          onChange={e => upd('category_code', e.target.value)} dir="ltr"
          placeholder="يُترك فارغاً إذا تم تحديد كود الصنف" />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">نوع الحافز</label>
          <select className="input w-full" value={form.incentive_type}
            onChange={e => upd('incentive_type', e.target.value)}>
            <option value="percent">نسبة مئوية %</option>
            <option value="fixed">مبلغ ثابت / وحدة</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">
            {form.incentive_type === 'percent' ? 'النسبة (%)' : 'المبلغ لكل وحدة'}
          </label>
          <input type="number" className="input w-full" value={form.incentive_value}
            onChange={e => upd('incentive_value', e.target.value)}
            step="0.01" min="0" dir="ltr" />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">الحد الأدنى للكمية</label>
          <input type="number" className="input w-full" value={form.min_qty}
            onChange={e => upd('min_qty', e.target.value)}
            step="1" min="0" dir="ltr" />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">فلتر كود المندوب</label>
          <input className="input w-full" value={form.person_code_filter}
            onChange={e => upd('person_code_filter', e.target.value)} dir="ltr"
            placeholder="فارغ = الكل" />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">الأولوية</label>
          <input type="number" className="input w-full" value={form.priority}
            onChange={e => upd('priority', e.target.value)}
            step="1" min="0" dir="ltr" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-gray-500 mb-1 block">أيام الصلاحية (اختياري)</label>
          <input type="number" className="input w-full" value={form.expiry_within_days}
            onChange={e => upd('expiry_within_days', e.target.value)}
            step="1" min="1" dir="ltr" placeholder="فارغ = لا قيد" />
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

function RulesTab({ selectedProgram }) {
  const [rules, setRules]       = useState([])
  const [loading, setLoading]   = useState(false)
  const [addingNew, setAddingNew] = useState(false)
  const [editingId, setEditingId] = useState(null)

  const load = useCallback(async () => {
    if (!selectedProgram) return
    setLoading(true)
    try {
      const { data } = await incentivesApi.listRules({ program: selectedProgram.id })
      setRules(data.results || data)
    } finally {
      setLoading(false)
    }
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
            onSaved={r => { setAddingNew(false); setRules(rs => [r, ...rs]) }}
            onCancel={() => setAddingNew(false)}
          />
        </div>
      )}

      {loading ? <Spinner /> : rules.length === 0 ? (
        <EmptyState icon="📐" title="لا توجد قواعد" sub="أضف قاعدة حوافز للبدء" />
      ) : (
        <div className="space-y-2">
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
                    <div>
                      <div className="font-medium text-gray-800">
                        {r.rule_name || (r.item_name || r.item_code || `فئة ${r.category_code}`)}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 mt-1.5">
                        {r.item_code && (
                          <Badge color="blue">صنف: {r.item_code}</Badge>
                        )}
                        {r.category_code && !r.item_code && (
                          <Badge color="purple">فئة: {r.category_code}</Badge>
                        )}
                        <Badge color={r.incentive_type === 'percent' ? 'green' : 'yellow'}>
                          {r.incentive_type === 'percent' ? `${r.incentive_value}%` : `${fmt(r.incentive_value)} / وحدة`}
                        </Badge>
                        {Number(r.min_qty) > 0 && (
                          <Badge color="gray">حد أدنى: {r.min_qty}</Badge>
                        )}
                        {r.person_code_filter && (
                          <Badge color="gray">مندوب: {r.person_code_filter}</Badge>
                        )}
                        {r.expiry_within_days && (
                          <Badge color="red">صلاحية &lt; {r.expiry_within_days} يوم</Badge>
                        )}
                        <Badge color="gray">أولوية: {r.priority}</Badge>
                        {!r.is_active && <Badge color="red">موقفة</Badge>}
                      </div>
                    </div>
                    <div className="flex gap-2 flex-shrink-0">
                      <button
                        className="text-xs text-blue-600 hover:text-blue-800 px-2"
                        onClick={() => setEditingId(r.id)}
                      >تعديل</button>
                      <button
                        className="text-xs text-red-500 hover:text-red-700 px-2"
                        onClick={() => deleteRule(r.id)}
                      >حذف</button>
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
// Calculate tab
// ─────────────────────────────────────────────────────────────────────────────

function CalculateTab({ selectedProgram }) {
  const [form, setForm] = useState({
    period_start: monthStart(),
    period_end: monthEnd(),
  })
  const [running, setRunning] = useState(false)
  const [result, setResult]   = useState(null)
  const [err, setErr]         = useState('')

  const run = async () => {
    if (!selectedProgram) { setErr('اختر برنامجاً أولاً'); return }
    setRunning(true); setErr(''); setResult(null)
    try {
      const { data } = await incentivesApi.calculate(selectedProgram.id, {
        period_start: form.period_start,
        period_end:   form.period_end,
      })
      setResult(data)
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل الاحتساب')
    } finally {
      setRunning(false)
    }
  }

  const userEntries = result
    ? Object.entries(result.total_by_user).sort((a, b) => b[1] - a[1])
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
          {err && <div className="text-sm text-red-600 bg-red-50 p-2 rounded">{err}</div>}
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

          <div className="pt-1">
            <button className="btn-primary w-full py-3" onClick={run}
              disabled={running || !selectedProgram}>
              {running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                  جارٍ الاحتساب من SOFTECH...
                </span>
              ) : '⚡ تشغيل الاحتساب'}
            </button>
          </div>
        </div>
      </div>

      {result && (
        <div>
          <div className="flex items-center gap-3 mb-3">
            <h3 className="font-semibold text-gray-700">نتائج الاحتساب</h3>
            <Badge color="green">{result.created} حركة</Badge>
          </div>

          {userEntries.length === 0 ? (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
              لم يتم العثور على حركات مطابقة للقواعد في هذه الفترة.
              تأكد من صحة كودات الأصناف والمندوبين.
            </div>
          ) : (
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <div className="bg-gray-50 px-4 py-2 border-b flex justify-between text-xs font-medium text-gray-500">
                <span>المندوب</span>
                <span>إجمالي الحوافز</span>
              </div>
              {userEntries.map(([uid, total]) => (
                <div key={uid} className="px-4 py-3 border-b last:border-0 flex justify-between items-center">
                  <span className="text-sm text-gray-700">مندوب #{uid}</span>
                  <span className="font-bold text-brand-700">{fmt(total)} ج.م</span>
                </div>
              ))}
              <div className="px-4 py-3 bg-gray-50 flex justify-between font-bold">
                <span>الإجمالي</span>
                <span className="text-brand-700">
                  {fmt(userEntries.reduce((s, [, v]) => s + v, 0))} ج.م
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Report tab
// ─────────────────────────────────────────────────────────────────────────────

function TransactionDrillDown({ programId, userId, periodStart, periodEnd, onClose }) {
  const [rows, setRows]   = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    incentivesApi
      .report(programId, { period_start: periodStart, period_end: periodEnd, user_id: userId })
      .then(({ data }) => {
        const found = data.rows?.find(r => r.user_id === userId)
        setRows(found?.transactions || [])
      })
      .finally(() => setLoading(false))
  }, [programId, userId, periodStart, periodEnd])

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 overflow-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl my-8">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="font-bold">تفصيل حركات المندوب</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <div className="overflow-auto max-h-[70vh]">
          {loading ? <Spinner /> : rows.length === 0 ? (
            <EmptyState icon="📋" title="لا توجد حركات" />
          ) : (
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
                        {t.doc_type === 'return' ? 'مرتجع' : 'بيع'}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-right">{fmt(t.quantity, 0)}</td>
                    <td className="px-3 py-2 text-right">{fmt(t.unit_price)}</td>
                    <td className={`px-3 py-2 text-right font-bold ${
                      Number(t.incentive_amount) < 0 ? 'text-red-600' : 'text-green-700'
                    }`}>
                      {fmt(t.incentive_amount)}
                    </td>
                    <td className="px-3 py-2">
                      {t.is_reversed && <Badge color="red">مُعكوس</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function ReportTab({ selectedProgram }) {
  const [form, setForm] = useState({
    period_start: monthStart(),
    period_end: monthEnd(),
  })
  const [rows, setRows]       = useState([])
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
        period_start: form.period_start,
        period_end:   form.period_end,
      })
      setRows(data.rows || [])
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل تحميل التقرير')
    } finally {
      setLoading(false)
    }
  }

  const finalize = async () => {
    if (!window.confirm('هل تريد اعتماد التسويات نهائياً لهذه الفترة؟ لا يمكن التراجع.')) return
    setFinalizing(true); setFinalMsg('')
    try {
      const { data } = await incentivesApi.finalize(selectedProgram.id, {
        period_start: form.period_start,
        period_end:   form.period_end,
      })
      setFinalMsg(`تم الاعتماد: ${data.finalized_count} مندوب / تم تجاوز: ${data.skipped_count}`)
      loadReport()
    } catch (e) {
      setFinalMsg(e.response?.data?.detail || 'فشل الاعتماد')
    } finally {
      setFinalizing(false)
    }
  }

  const grandTotal = rows.reduce((s, r) => s + (r.total_incentive || 0), 0)

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
            <div className="bg-gray-50 px-4 py-3 border-b flex justify-between items-center">
              <span className="text-sm font-semibold text-gray-700">
                {rows.length} مندوب — {form.period_start} → {form.period_end}
              </span>
              <div className="flex items-center gap-2 text-sm font-bold text-brand-700">
                إجمالي: {fmt(grandTotal)} ج.م
              </div>
            </div>

            <table className="w-full">
              <thead className="bg-gray-50/50">
                <tr>
                  {['المندوب', 'كود المندوب', 'مبيعات', 'مرتجعات', 'إجمالي الحوافز', 'الحالة', ''].map(h => (
                    <th key={h} className="px-4 py-2 text-right text-xs text-gray-500 font-medium">{h}</th>
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
                    <td className="px-4 py-3">
                      <Badge color={r.is_finalized ? 'green' : 'yellow'}>
                        {r.is_finalized ? 'مُعتمد' : 'مسودة'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        className="text-xs text-brand-600 hover:text-brand-800 underline"
                        onClick={() => setDrillUser(r.user_id)}
                      >تفصيل</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="px-4 py-3 border-t bg-gray-50 flex items-center justify-between">
              {finalMsg && (
                <div className="text-sm text-green-700">{finalMsg}</div>
              )}
              <div className="mr-auto">
                <button
                  className="btn-primary text-sm"
                  onClick={finalize}
                  disabled={finalizing || rows.every(r => r.is_finalized)}
                >
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
// Settlements tab  +  Printable Receipt
// ─────────────────────────────────────────────────────────────────────────────

function ReceiptModal({ settlementId, onClose }) {
  const [data, setData] = useState(null)
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
      <!DOCTYPE html><html dir="rtl" lang="ar">
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
        </style>
      </head>
      <body>${content}</body></html>
    `)
    win.document.close()
    win.print()
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 overflow-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl my-8">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="font-bold">إيصال تسوية الحوافز</h2>
          <div className="flex gap-2">
            <button className="btn-secondary text-sm" onClick={handlePrint}>🖨 طباعة</button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
          </div>
        </div>

        <div className="p-6" ref={printRef}>
          {loading ? <Spinner /> : !data ? null : (
            <>
              <div className="header mb-4">
                <div className="text-xl font-bold">صيدليات الرزيقي</div>
                <div className="text-sm text-gray-500 mt-1">إيصال تسوية حوافز المبيعات</div>
              </div>

              <div className="grid grid-cols-2 gap-4 mb-4 text-sm">
                <div>
                  <div className="text-gray-500 text-xs">البرنامج</div>
                  <div className="font-semibold">{data.settlement.program_name}</div>
                </div>
                <div>
                  <div className="text-gray-500 text-xs">المندوب</div>
                  <div className="font-semibold">{data.settlement.user_name}</div>
                </div>
                <div>
                  <div className="text-gray-500 text-xs">الفترة</div>
                  <div className="font-semibold">
                    {data.settlement.period_start} → {data.settlement.period_end}
                  </div>
                </div>
                <div>
                  <div className="text-gray-500 text-xs">تاريخ الاعتماد</div>
                  <div className="font-semibold">
                    {data.settlement.finalized_at?.slice(0, 10) || '—'}
                  </div>
                </div>
              </div>

              <div className="bg-brand-50 border border-brand-200 rounded-lg p-3 mb-4 flex justify-between items-center">
                <span className="text-sm text-gray-600">إجمالي الحوافز المستحقة</span>
                <span className="total">{fmt(data.settlement.total_incentive)} ج.م</span>
              </div>

              <div className="font-semibold text-sm mb-2">تفصيل الأصناف</div>
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th>الصنف</th>
                    <th>القاعدة</th>
                    <th>الكمية الصافية</th>
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
                      <td className="text-gray-500">{s.rule_name || '—'}</td>
                      <td className="text-right">{fmt(s.net_qty, 0)}</td>
                      <td className={`text-right font-bold ${Number(s.total_incentive) < 0 ? 'text-red-600' : 'text-green-700'}`}>
                        {fmt(s.total_incentive)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {data.settlement.notes && (
                <div className="mt-4 text-sm text-gray-500 border-t pt-3">
                  ملاحظات: {data.settlement.notes}
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
    } finally {
      setLoading(false)
    }
  }, [programFilter])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (selectedProgram) setProgramFilter(selectedProgram.id) }, [selectedProgram])

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-bold text-gray-700">تسويات مُعتمدة</h2>
        <button className="btn-secondary text-sm" onClick={load}>↻ تحديث</button>
      </div>

      {loading ? <Spinner /> : settlements.length === 0 ? (
        <EmptyState icon="✅" title="لا توجد تسويات مُعتمدة" sub="اعتمد تقريراً من تبويب التقرير" />
      ) : (
        <div className="space-y-2">
          {settlements.map(s => (
            <div key={s.id} className="bg-white border border-gray-200 rounded-xl p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold text-gray-800">{s.user_name}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{s.program_name}</div>
                  <div className="text-xs text-gray-400 mt-1">
                    {s.period_start} → {s.period_end}
                    &nbsp;·&nbsp; {s.transaction_count} حركة
                    &nbsp;·&nbsp; اعتمد: {s.finalized_by_name || '—'} في {s.finalized_at?.slice(0, 10)}
                  </div>
                </div>
                <div className="text-left flex flex-col items-end gap-2">
                  <span className="font-bold text-brand-700 text-lg">{fmt(s.total_incentive)} ج.م</span>
                  <button
                    className="btn-secondary text-xs"
                    onClick={() => setReceiptId(s.id)}
                  >🖨 إيصال</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {receiptId && (
        <ReceiptModal settlementId={receiptId} onClose={() => setReceiptId(null)} />
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Root page component
// ─────────────────────────────────────────────────────────────────────────────

export default function IncentivesPage() {
  const [activeTab, setActiveTab]           = useState('programs')
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
              <button
                className="text-gray-400 hover:text-gray-600 mr-1"
                onClick={() => setSelectedProgram(null)}
              >✕</button>
            </div>
          )}
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 mt-4 border-b -mb-4">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === t.id
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {t.icon} {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'programs' && (
          <ProgramsTab selectedProgram={selectedProgram} onSelect={handleSelectProgram} />
        )}
        {activeTab === 'rules' && (
          <RulesTab selectedProgram={selectedProgram} />
        )}
        {activeTab === 'calculate' && (
          <CalculateTab selectedProgram={selectedProgram} />
        )}
        {activeTab === 'report' && (
          <ReportTab selectedProgram={selectedProgram} />
        )}
        {activeTab === 'settlements' && (
          <SettlementsTab selectedProgram={selectedProgram} />
        )}
      </div>
    </div>
  )
}
