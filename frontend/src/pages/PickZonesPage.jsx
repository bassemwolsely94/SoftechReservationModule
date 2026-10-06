/**
 * PickZonesPage.jsx  —  إدارة مناطق التجميع (ورقة التجميع)
 *
 * Full management console for the replenishment picking-sheet classification:
 *   • Location switcher — the DEFAULT config or a per-warehouse config
 *     (a supplying branch with its own zones gets its own pick path; branches
 *     without one fall back to the default). "نسخ الإعداد الافتراضي" bootstraps
 *     a branch config from the default.
 *   • المناطق    — zones: name, pick-path order, warehouse location,
 *                  active toggle + special roles (غوالي/ثلاجة/غير مصنف)
 *   • القواعد    — rules: match by item-NAME keywords OR by item-master
 *                  columns (شكل الصنف/نوع الدواء/العائلة/الشركة/المنشأ/الوحدة)
 *                  with value dropdowns from the catalog lookups; ordered
 *                  evaluation (first match wins) with up/down reordering
 *                  + live tester
 *   • غير مصنف   — catalog items matching no rule → assign zone / tag
 *   • التخصيصات  — explicit per-item assignments (beat all rules) with tags
 *
 * Classification precedence (enforced by the backend):
 *   تخصيص يدوي ← ثلاجة (علامة الكتالوج أو كلمة FRIDGE) ← حد الغوالي ← القواعد ← غير مصنف
 *
 * Write access: admin + purchasing (read-only for other roles).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pickZonesApi, branchesApi } from '../api/client'
import ItemSearchInput from '../components/ItemSearchInput'
import useAuthStore from '../store/authStore'

const toLatin = s =>
  s == null ? '' : String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660))

const PURPOSES = [
  { value: 'picking',  label: '🚚 تجميع — مخزن المصدر',  hint: 'مسار التجميع بالمخزن المورد (ورقة التجميع)' },
  { value: 'stocking', label: '🗄️ ترصيص — أرفف الفرع',  hint: 'ترتيب أرفف الفرع المستلم (ورقة الترصيص + الجرد)' },
]

const ROLE_BADGES = [
  { flag: 'is_price_zone',  label: '💰 غوالي',     title: 'تستقبل الأصناف الأغلى من حد الغوالي' },
  { flag: 'is_fridge_zone', label: '🧊 ثلاجة',     title: 'تستقبل أصناف الثلاجة (علامة الكتالوج أو كلمة FRIDGE)' },
  { flag: 'is_fallback',    label: '❓ غير مصنف',  title: 'تستقبل الأصناف التي لا تطابق أي قاعدة' },
]

const MATCH_FIELDS = [
  { value: 'name',          label: 'اسم الصنف (كلمات)' },
  { value: 'shape',         label: 'شكل الصنف' },
  { value: 'medicine_type', label: 'نوع الدواء' },
  { value: 'family',        label: 'عائلة الصنف' },
  { value: 'producer',      label: 'الشركة المنتجة' },
  { value: 'origin',        label: 'بلد المنشأ' },
  { value: 'unit',          label: 'وحدة العبوة' },
]
const MATCH_FIELD_LABEL = Object.fromEntries(MATCH_FIELDS.map(f => [f.value, f.label]))

function errMsg(e, fallback) {
  return e?.response?.data?.detail
    || (typeof e?.response?.data === 'object' ? JSON.stringify(e.response.data) : null)
    || fallback
}

// branchParam: '' = default config, otherwise a branch id (number)
const branchBody = (branchParam) => (branchParam === '' ? null : Number(branchParam))

// ── Field-value multi-picker (dropdown fed by the item-master lookups) ────────

function FieldValuePicker({ field, values, onChange, disabled }) {
  const { data, isLoading } = useQuery({
    queryKey: ['pick-field-values', field],
    queryFn: () => pickZonesApi.fieldValues(field).then(r => r.data.values),
    staleTime: 300_000,
    enabled: field !== 'name',
  })
  const labelOf = (v) => data?.find(x => x.value === v)?.label || v

  return (
    <div className="flex flex-wrap items-center gap-1">
      {values.map(v => (
        <span key={v}
          className="inline-flex items-center gap-1 text-[11px] bg-brand-50 text-brand-700 px-2 py-0.5 rounded-full">
          {labelOf(v)}
          {!disabled && (
            <button onClick={() => onChange(values.filter(x => x !== v))}
              className="text-brand-400 hover:text-brand-800">✕</button>
          )}
        </span>
      ))}
      {!disabled && (
        <select
          className="input-field text-xs w-44"
          value=""
          disabled={isLoading}
          onChange={e => {
            const v = e.target.value
            if (v && !values.includes(v)) onChange([...values, v])
          }}>
          <option value="">{isLoading ? 'تحميل القيم...' : '+ أضف قيمة...'}</option>
          {(data || []).filter(x => !values.includes(x.value)).map(x => (
            <option key={x.value} value={x.value}>
              {x.label} ({toLatin(x.count)})
            </option>
          ))}
        </select>
      )}
    </div>
  )
}

// ── Settings card (threshold + special-role selectors) ────────────────────────

function SettingsCard({ zones, canEdit, showToast }) {
  const qc = useQueryClient()
  const { data: settings } = useQuery({
    queryKey: ['pick-zone-settings'],
    queryFn: () => pickZonesApi.getSettings().then(r => r.data),
  })
  const [threshold, setThreshold] = useState(null)

  const saveThreshold = useMutation({
    mutationFn: (v) => pickZonesApi.saveSettings({ price_threshold: v }),
    onSuccess: () => {
      qc.invalidateQueries(['pick-zone-settings'])
      showToast('✅ تم حفظ حد الغوالي')
      setThreshold(null)
    },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الحفظ')}`),
  })

  const setRole = useMutation({
    mutationFn: ({ id, flag }) => pickZonesApi.updateZone(id, { [flag]: true }),
    onSuccess: () => { qc.invalidateQueries(['pick-zones']); showToast('✅ تم تحديث الدور') },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في التحديث')}`),
  })

  const currentThreshold = threshold ?? settings?.price_threshold ?? ''

  return (
    <div className="card mb-4">
      <div className="font-bold text-gray-800 text-sm mb-3">⚙️ إعدادات التصنيف</div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div>
          <label className="text-xs text-gray-500 font-semibold block mb-1">
            حد سعر الغوالي (ج.م) — عام لكل المخازن
          </label>
          <div className="flex gap-2">
            <input
              type="number" min="1"
              className="input-field text-sm w-28"
              value={currentThreshold}
              disabled={!canEdit}
              onChange={e => setThreshold(e.target.value)}
            />
            {threshold != null && Number(threshold) > 0 && (
              <button
                onClick={() => saveThreshold.mutate(Number(threshold))}
                disabled={saveThreshold.isPending}
                className="btn-secondary text-xs px-3"
              >
                حفظ
              </button>
            )}
          </div>
          <div className="text-[10px] text-gray-400 mt-1">
            الصنف بسعر أعلى أو يساوي هذا الحد → منطقة الغوالي
          </div>
        </div>

        {ROLE_BADGES.map(({ flag, label, title }) => {
          const holder = zones.find(z => z[flag])
          return (
            <div key={flag} title={title}>
              <label className="text-xs text-gray-500 font-semibold block mb-1">{label}</label>
              <select
                className="input-field text-sm w-full"
                value={holder?.id || ''}
                disabled={!canEdit || setRole.isPending}
                onChange={e => e.target.value && setRole.mutate({ id: Number(e.target.value), flag })}
              >
                <option value="">— غير محددة —</option>
                {zones.map(z => (
                  <option key={z.id} value={z.id}>{z.name}</option>
                ))}
              </select>
            </div>
          )
        })}
      </div>
      <div className="text-[11px] text-gray-400 mt-3 bg-gray-50 rounded-lg px-3 py-2">
        🧭 ترتيب التصنيف: <b>تخصيص يدوي للصنف</b> ← <b>ثلاجة</b> (علامة الكتالوج أو كلمة FRIDGE بالاسم)
        ← <b>حد الغوالي</b> ← <b>القواعد</b> بالترتيب (أول تطابق يفوز) ← <b>غير مصنف</b>
      </div>
    </div>
  )
}

// ── Zones tab ─────────────────────────────────────────────────────────────────

function ZoneRow({ zone, canEdit, showToast }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({
    name: zone.name, sort_key: zone.sort_key, location: zone.location || '',
  })
  const dirty = form.name !== zone.name
    || Number(form.sort_key) !== zone.sort_key
    || form.location !== (zone.location || '')

  const update = useMutation({
    mutationFn: (data) => pickZonesApi.updateZone(zone.id, data),
    onSuccess: () => { qc.invalidateQueries(['pick-zones']); showToast('✅ تم الحفظ') },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الحفظ')}`),
  })
  const remove = useMutation({
    mutationFn: () => pickZonesApi.deleteZone(zone.id),
    onSuccess: () => { qc.invalidateQueries(['pick-zones']); qc.invalidateQueries(['pick-rules']); showToast('🗑️ حُذفت المنطقة') },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الحذف')}`),
  })

  function confirmDelete() {
    const parts = []
    if (zone.rule_count)     parts.push(`${zone.rule_count} قاعدة`)
    if (zone.override_count) parts.push(`${zone.override_count} تخصيص صنف`)
    const extra = parts.length ? `\nسيُحذف معها: ${parts.join(' و ')}.` : ''
    if (window.confirm(`حذف منطقة "${zone.name}"؟${extra}`)) remove.mutate()
  }

  return (
    <tr className={`border-b border-gray-50 ${zone.is_active ? '' : 'opacity-50 bg-gray-50'}`}>
      <td className="px-3 py-2 w-24">
        <input type="number" className="input-field text-sm w-20 text-center" disabled={!canEdit}
          value={form.sort_key}
          onChange={e => setForm(f => ({ ...f, sort_key: e.target.value }))} />
      </td>
      <td className="px-3 py-2">
        <input className="input-field text-sm w-full font-semibold" disabled={!canEdit}
          value={form.name}
          onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
      </td>
      <td className="px-3 py-2">
        <input className="input-field text-sm w-full" disabled={!canEdit}
          placeholder="مثال: ممر 2 — رف B"
          value={form.location}
          onChange={e => setForm(f => ({ ...f, location: e.target.value }))} />
      </td>
      <td className="px-3 py-2 text-center whitespace-nowrap">
        {ROLE_BADGES.filter(r => zone[r.flag]).map(r => (
          <span key={r.flag} title={r.title}
            className="text-[10px] bg-brand-50 text-brand-700 px-1.5 py-0.5 rounded-full mx-0.5">
            {r.label}
          </span>
        ))}
      </td>
      <td className="px-3 py-2 text-center text-xs text-gray-500 tabular-nums">
        {toLatin(zone.rule_count)} / {toLatin(zone.override_count)}
      </td>
      <td className="px-3 py-2 text-center">
        <input type="checkbox" className="accent-brand-600 cursor-pointer"
          checked={zone.is_active} disabled={!canEdit}
          onChange={() => update.mutate({ is_active: !zone.is_active })} />
      </td>
      {canEdit && (
        <td className="px-3 py-2 text-left whitespace-nowrap">
          {dirty && (
            <button onClick={() => update.mutate({
              name: form.name.trim(),
              sort_key: Number(form.sort_key) || 0,
              location: form.location.trim(),
            })}
              disabled={update.isPending}
              className="text-xs bg-brand-600 hover:bg-brand-700 text-white font-bold px-3 py-1 rounded-lg ml-1">
              حفظ
            </button>
          )}
          <button onClick={confirmDelete} disabled={remove.isPending}
            className="text-xs text-red-500 hover:text-red-700 px-2 py-1" title="حذف المنطقة">
            🗑️
          </button>
        </td>
      )}
    </tr>
  )
}

function ZonesTab({ zones, branchParam, purpose, canEdit, showToast }) {
  const qc = useQueryClient()
  const [add, setAdd] = useState({ name: '', sort_key: '', location: '' })

  const create = useMutation({
    mutationFn: () => pickZonesApi.createZone({
      branch: branchBody(branchParam),
      purpose,
      name: add.name.trim(),
      sort_key: Number(add.sort_key) || 100,
      location: add.location.trim(),
    }),
    onSuccess: () => {
      qc.invalidateQueries(['pick-zones'])
      setAdd({ name: '', sort_key: '', location: '' })
      showToast('✅ أُضيفت المنطقة')
    },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الإضافة')}`),
  })

  return (
    <div>
      <SettingsCard zones={zones} canEdit={canEdit} showToast={showToast} />
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-24"
                title="الأصغر يُجمَّع أولاً — يحدد مسار السير في المخزن">ترتيب المسار</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500">اسم المنطقة</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500">الموقع / الرف</th>
              <th className="text-center px-3 py-2.5 text-xs font-semibold text-gray-500">أدوار خاصة</th>
              <th className="text-center px-3 py-2.5 text-xs font-semibold text-gray-500"
                title="عدد القواعد / تخصيصات الأصناف">قواعد/تخصيصات</th>
              <th className="text-center px-3 py-2.5 text-xs font-semibold text-gray-500">مفعّلة</th>
              {canEdit && <th className="px-3 py-2.5 w-28" />}
            </tr>
          </thead>
          <tbody>
            {zones.map(z => (
              <ZoneRow key={z.id} zone={z} canEdit={canEdit} showToast={showToast} />
            ))}
            {canEdit && (
              <tr className="bg-brand-50/40">
                <td className="px-3 py-2">
                  <input type="number" className="input-field text-sm w-20 text-center"
                    placeholder="150" value={add.sort_key}
                    onChange={e => setAdd(a => ({ ...a, sort_key: e.target.value }))} />
                </td>
                <td className="px-3 py-2">
                  <input className="input-field text-sm w-full" placeholder="اسم منطقة جديدة..."
                    value={add.name}
                    onChange={e => setAdd(a => ({ ...a, name: e.target.value }))} />
                </td>
                <td className="px-3 py-2">
                  <input className="input-field text-sm w-full" placeholder="الموقع (اختياري)"
                    value={add.location}
                    onChange={e => setAdd(a => ({ ...a, location: e.target.value }))} />
                </td>
                <td colSpan={3} />
                <td className="px-3 py-2 text-left">
                  <button
                    onClick={() => create.mutate()}
                    disabled={!add.name.trim() || create.isPending}
                    className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white font-bold px-3 py-1.5 rounded-lg disabled:opacity-40">
                    + إضافة
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Rules tab ─────────────────────────────────────────────────────────────────

function RuleTester({ branchParam, purpose, showToast }) {
  const [form, setForm] = useState({ name: '', price: '', requires_fridge: false })
  const [result, setResult] = useState(null)

  const test = useMutation({
    mutationFn: () => pickZonesApi.preview({
      name: form.name.trim(),
      price: form.price === '' ? null : Number(form.price),
      requires_fridge: form.requires_fridge,
      branch: branchBody(branchParam),
      purpose,
    }),
    onSuccess: (r) => setResult(r.data),
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الاختبار')}`),
  })

  return (
    <div className="card mb-4 bg-indigo-50/50 border border-indigo-100">
      <div className="font-bold text-gray-800 text-sm mb-2">🧪 اختبار التصنيف الحي</div>
      <div className="flex flex-wrap gap-2 items-center">
        <input className="input-field text-sm flex-1 min-w-56"
          placeholder="اكتب اسم صنف... مثال: PANADOL EXTRA 24TAB"
          value={form.name}
          onChange={e => { setForm(f => ({ ...f, name: e.target.value })); setResult(null) }}
          onKeyDown={e => e.key === 'Enter' && form.name.trim() && test.mutate()} />
        <input type="number" className="input-field text-sm w-28" placeholder="السعر"
          value={form.price}
          onChange={e => { setForm(f => ({ ...f, price: e.target.value })); setResult(null) }} />
        <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer">
          <input type="checkbox" className="accent-brand-600"
            checked={form.requires_fridge}
            onChange={e => { setForm(f => ({ ...f, requires_fridge: e.target.checked })); setResult(null) }} />
          🧊 صنف ثلاجة
        </label>
        <button onClick={() => test.mutate()}
          disabled={!form.name.trim() || test.isPending}
          className="text-xs bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-4 py-2 rounded-lg disabled:opacity-40">
          {test.isPending ? '...' : 'اختبر'}
        </button>
      </div>
      {result && (
        <div className="mt-3 flex items-center gap-3 bg-white rounded-xl px-4 py-2.5 border border-indigo-100">
          <span className="text-sm">النتيجة:</span>
          <span className="font-black text-brand-700">{result.zone_name || '—'}</span>
          <span className="text-xs text-gray-400">({result.reason})</span>
          {result.tag && <span className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full">🏷️ {result.tag}</span>}
        </div>
      )}
    </div>
  )
}

function RuleRow({ rule, idx, total, zones, canEdit, onMove, showToast }) {
  const qc = useQueryClient()
  const isName = rule.match_field === 'name'
  const [kwText, setKwText] = useState((rule.keywords || []).join('، '))
  const [values, setValues] = useState(rule.keywords || [])
  const [note, setNote]     = useState(rule.note || '')
  const parseKw = (s) => s.split(/[,،]/).map(k => k.trim()).filter(Boolean)
  const currentValues = isName ? parseKw(kwText) : values
  const dirty = JSON.stringify(currentValues) !== JSON.stringify(rule.keywords || [])
    || note !== (rule.note || '')

  const update = useMutation({
    mutationFn: (data) => pickZonesApi.updateRule(rule.id, data),
    onSuccess: () => { qc.invalidateQueries(['pick-rules']); showToast('✅ تم الحفظ') },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الحفظ')}`),
  })
  const remove = useMutation({
    mutationFn: () => pickZonesApi.deleteRule(rule.id),
    onSuccess: () => { qc.invalidateQueries(['pick-rules']); showToast('🗑️ حُذفت القاعدة') },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الحذف')}`),
  })

  return (
    <tr className={`border-b border-gray-50 ${rule.is_active ? '' : 'opacity-50 bg-gray-50'}`}>
      <td className="px-2 py-2 text-center whitespace-nowrap w-20">
        <span className="font-black text-gray-400 tabular-nums text-xs ml-1">{toLatin(idx + 1)}</span>
        {canEdit && (
          <span className="inline-flex flex-col align-middle">
            <button onClick={() => onMove(idx, -1)} disabled={idx === 0}
              className="text-gray-400 hover:text-brand-600 disabled:opacity-20 leading-none text-xs">▲</button>
            <button onClick={() => onMove(idx, +1)} disabled={idx === total - 1}
              className="text-gray-400 hover:text-brand-600 disabled:opacity-20 leading-none text-xs">▼</button>
          </span>
        )}
      </td>
      <td className="px-3 py-2 w-40">
        <select className="input-field text-sm w-full" disabled={!canEdit}
          value={rule.zone}
          onChange={e => update.mutate({ zone: Number(e.target.value) })}>
          {zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
        </select>
      </td>
      <td className="px-3 py-2 w-40">
        <select className="input-field text-sm w-full" disabled={!canEdit}
          value={rule.match_field}
          onChange={e => update.mutate({ match_field: e.target.value, keywords: [] })}
          title="اسم الصنف = بحث كلمات؛ الباقي = مطابقة قيمة من جدول الأصناف">
          {MATCH_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
      </td>
      <td className="px-3 py-2">
        {isName ? (
          <input className="input-field text-sm w-full font-mono" dir="ltr" disabled={!canEdit}
            placeholder="TAB, CAP, LOZENG"
            value={kwText}
            onChange={e => setKwText(e.target.value)} />
        ) : (
          <FieldValuePicker field={rule.match_field} values={values}
            onChange={setValues} disabled={!canEdit} />
        )}
      </td>
      <td className="px-3 py-2 w-36">
        <input className="input-field text-sm w-full" disabled={!canEdit}
          placeholder="ملاحظة" value={note}
          onChange={e => setNote(e.target.value)} />
      </td>
      <td className="px-3 py-2 text-center">
        <input type="checkbox" className="accent-brand-600 cursor-pointer"
          checked={rule.is_active} disabled={!canEdit}
          onChange={() => update.mutate({ is_active: !rule.is_active })} />
      </td>
      {canEdit && (
        <td className="px-3 py-2 text-left whitespace-nowrap w-28">
          {dirty && (
            <button onClick={() => update.mutate({ keywords: currentValues, note: note.trim() })}
              disabled={update.isPending || currentValues.length === 0}
              className="text-xs bg-brand-600 hover:bg-brand-700 text-white font-bold px-3 py-1 rounded-lg ml-1 disabled:opacity-40">
              حفظ
            </button>
          )}
          <button onClick={() => window.confirm('حذف القاعدة؟') && remove.mutate()}
            className="text-xs text-red-500 hover:text-red-700 px-2 py-1">🗑️</button>
        </td>
      )}
    </tr>
  )
}

function RulesTab({ zones, branchParam, purpose, canEdit, showToast }) {
  const qc = useQueryClient()
  const { data: rules = [] } = useQuery({
    queryKey: ['pick-rules', branchParam, purpose],
    queryFn: () => pickZonesApi.listRules({ branch: branchParam, purpose })
      .then(r => r.data.results || r.data),
  })
  const [add, setAdd] = useState({ zone: '', match_field: 'name', keywords: '', values: [] })

  const reorder = useMutation({
    mutationFn: (ids) => pickZonesApi.reorderRules(ids),
    onSuccess: () => qc.invalidateQueries(['pick-rules']),
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في إعادة الترتيب')}`),
  })
  const create = useMutation({
    mutationFn: () => pickZonesApi.createRule({
      zone: Number(add.zone),
      match_field: add.match_field,
      keywords: add.match_field === 'name'
        ? add.keywords.split(/[,،]/).map(k => k.trim()).filter(Boolean)
        : add.values,
      priority: (rules.length + 1) * 10,
    }),
    onSuccess: () => {
      qc.invalidateQueries(['pick-rules'])
      setAdd({ zone: '', match_field: 'name', keywords: '', values: [] })
      showToast('✅ أُضيفت القاعدة')
    },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الإضافة')}`),
  })

  function move(idx, dir) {
    const ids = rules.map(r => r.id)
    const j = idx + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[idx], ids[j]] = [ids[j], ids[idx]]
    reorder.mutate(ids)
  }

  const addValid = add.zone && (add.match_field === 'name'
    ? add.keywords.trim() : add.values.length > 0)

  return (
    <div>
      <RuleTester branchParam={branchParam} purpose={purpose} showToast={showToast} />
      <div className="text-xs text-gray-400 mb-2">
        القواعد تُقيَّم من أعلى لأسفل — <b>أول تطابق يفوز</b>. نوع المطابقة إما كلمات داخل اسم الصنف،
        أو قيمة من أعمدة جدول الأصناف الرئيسي (شكل الصنف، نوع الدواء، العائلة...) تُختار من قوائم منسدلة.
      </div>
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-center px-2 py-2.5 text-xs font-semibold text-gray-500 w-20">الترتيب</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-40">المنطقة</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-40">نوع المطابقة</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500">
                الكلمات / القيم <span className="font-normal text-gray-400">(أي تطابق واحد يكفي)</span>
              </th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-36">ملاحظة</th>
              <th className="text-center px-3 py-2.5 text-xs font-semibold text-gray-500">مفعّلة</th>
              {canEdit && <th className="px-3 py-2.5 w-28" />}
            </tr>
          </thead>
          <tbody>
            {rules.map((r, i) => (
              <RuleRow key={`${r.id}-${r.match_field}`} rule={r} idx={i} total={rules.length}
                zones={zones} canEdit={canEdit} onMove={move} showToast={showToast} />
            ))}
            {canEdit && (
              <tr className="bg-brand-50/40">
                <td className="px-2 py-2 text-center text-xs text-gray-400">جديدة</td>
                <td className="px-3 py-2">
                  <select className="input-field text-sm w-full" value={add.zone}
                    onChange={e => setAdd(a => ({ ...a, zone: e.target.value }))}>
                    <option value="">اختر منطقة...</option>
                    {zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
                  </select>
                </td>
                <td className="px-3 py-2">
                  <select className="input-field text-sm w-full" value={add.match_field}
                    onChange={e => setAdd(a => ({ ...a, match_field: e.target.value, keywords: '', values: [] }))}>
                    {MATCH_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                  </select>
                </td>
                <td className="px-3 py-2" colSpan={2}>
                  {add.match_field === 'name' ? (
                    <input className="input-field text-sm w-full font-mono" dir="ltr"
                      placeholder="SYRUP, SYP, ORAL SOL"
                      value={add.keywords}
                      onChange={e => setAdd(a => ({ ...a, keywords: e.target.value }))} />
                  ) : (
                    <FieldValuePicker field={add.match_field} values={add.values}
                      onChange={values => setAdd(a => ({ ...a, values }))} />
                  )}
                </td>
                <td className="px-3 py-2 text-left" colSpan={canEdit ? 2 : 1}>
                  <button onClick={() => create.mutate()}
                    disabled={!addValid || create.isPending}
                    className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white font-bold px-3 py-1.5 rounded-lg disabled:opacity-40">
                    + إضافة
                  </button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Uncategorized tab ─────────────────────────────────────────────────────────

function UncategorizedRow({ item, zones, branchParam, purpose, canEdit, showToast }) {
  const qc = useQueryClient()
  const [zoneId, setZoneId] = useState('')
  const [tag, setTag] = useState('')

  const assign = useMutation({
    mutationFn: () => pickZonesApi.createOverride({
      item_code: item.item_code, zone: Number(zoneId), tag: tag.trim(),
      branch: branchBody(branchParam), purpose,
    }),
    onSuccess: () => {
      qc.invalidateQueries(['pick-uncategorized'])
      qc.invalidateQueries(['pick-overrides'])
      qc.invalidateQueries(['pick-zones'])
      showToast(`✅ صُنِّف ${item.item_name}`)
    },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في التخصيص')}`),
  })

  return (
    <tr className="border-b border-gray-50">
      <td className="px-3 py-2 font-mono text-xs text-gray-500">{item.item_code}</td>
      <td className="px-3 py-2 text-sm">{item.item_name}
        {item.requires_fridge && <span className="mr-1" title="صنف ثلاجة">🧊</span>}
      </td>
      <td className="px-3 py-2 text-xs text-gray-500 tabular-nums">
        {item.price ? `${toLatin(item.price.toLocaleString())} ج.م` : '—'}
      </td>
      {canEdit && (
        <>
          <td className="px-3 py-2 w-44">
            <select className="input-field text-sm w-full" value={zoneId}
              onChange={e => setZoneId(e.target.value)}>
              <option value="">اختر منطقة...</option>
              {zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
          </td>
          <td className="px-3 py-2 w-36">
            <input className="input-field text-sm w-full" placeholder="وسم/رف (اختياري)"
              value={tag} onChange={e => setTag(e.target.value)} />
          </td>
          <td className="px-3 py-2 text-left w-24">
            <button onClick={() => assign.mutate()}
              disabled={!zoneId || assign.isPending}
              className="text-xs bg-brand-600 hover:bg-brand-700 text-white font-bold px-3 py-1.5 rounded-lg disabled:opacity-40">
              تخصيص
            </button>
          </td>
        </>
      )}
    </tr>
  )
}

function UncategorizedTab({ zones, branchParam, purpose, canEdit, showToast }) {
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['pick-uncategorized', branchParam, purpose, search],
    queryFn: () => pickZonesApi.uncategorized({
      q: search, limit: 150, branch: branchParam, purpose,
    }).then(r => r.data),
    staleTime: 60_000,
  })

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <input className="input-field text-sm w-72" placeholder="ابحث بالاسم أو الكود..."
          value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && setSearch(q.trim())} />
        <button onClick={() => setSearch(q.trim())} className="btn-secondary text-xs px-3 py-1.5">بحث</button>
        <button onClick={() => refetch()} className="btn-secondary text-xs px-3 py-1.5"
          disabled={isFetching}>
          {isFetching ? 'جارٍ الفحص...' : '🔄 إعادة الفحص'}
        </button>
        {data && (
          <span className="text-xs text-gray-400">
            {toLatin(data.count)} صنف غير مصنف
            {data.truncated && ' (أول دفعة — ضيّق البحث لرؤية المزيد)'}
            {' '}— فُحص {toLatin(data.scanned?.toLocaleString?.() || data.scanned)} صنف
          </span>
        )}
      </div>
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-24">الكود</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500">اسم الصنف</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-28">سعر الجمهور</th>
              {canEdit && (
                <>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-44">المنطقة</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-36">وسم</th>
                  <th className="px-3 py-2.5 w-24" />
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {isFetching && !data ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-gray-400 text-sm">
                جارٍ فحص الكتالوج مقابل القواعد الحالية...
              </td></tr>
            ) : (data?.results || []).length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-gray-400 text-sm">
                🎉 لا توجد أصناف غير مصنفة{search && ' مطابقة للبحث'}
              </td></tr>
            ) : (
              data.results.map(it => (
                <UncategorizedRow key={it.item_code} item={it} zones={zones}
                  branchParam={branchParam} purpose={purpose} canEdit={canEdit} showToast={showToast} />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Overrides tab ─────────────────────────────────────────────────────────────

function OverrideRow({ ov, zones, canEdit, showToast }) {
  const qc = useQueryClient()
  const [tag, setTag] = useState(ov.tag || '')

  const update = useMutation({
    mutationFn: (data) => pickZonesApi.updateOverride(ov.id, data),
    onSuccess: () => { qc.invalidateQueries(['pick-overrides']); showToast('✅ تم الحفظ') },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الحفظ')}`),
  })
  const remove = useMutation({
    mutationFn: () => pickZonesApi.deleteOverride(ov.id),
    onSuccess: () => {
      qc.invalidateQueries(['pick-overrides'])
      qc.invalidateQueries(['pick-uncategorized'])
      qc.invalidateQueries(['pick-zones'])
      showToast('🗑️ أُلغي التخصيص — يعود الصنف للقواعد العامة')
    },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الحذف')}`),
  })

  return (
    <tr className="border-b border-gray-50">
      <td className="px-3 py-2 font-mono text-xs text-gray-500">{ov.item_softech_id}</td>
      <td className="px-3 py-2 text-sm">{ov.item_name}</td>
      <td className="px-3 py-2 w-44">
        <select className="input-field text-sm w-full" disabled={!canEdit}
          value={ov.zone}
          onChange={e => update.mutate({ zone: Number(e.target.value) })}>
          {zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
        </select>
      </td>
      <td className="px-3 py-2 w-40">
        <div className="flex gap-1">
          <input className="input-field text-sm w-full" disabled={!canEdit}
            placeholder="وسم/رف" value={tag}
            onChange={e => setTag(e.target.value)} />
          {canEdit && tag !== (ov.tag || '') && (
            <button onClick={() => update.mutate({ tag: tag.trim() })}
              className="text-xs bg-brand-600 text-white font-bold px-2 rounded-lg">✓</button>
          )}
        </div>
      </td>
      <td className="px-3 py-2 text-xs text-gray-400">{ov.created_by_name}</td>
      {canEdit && (
        <td className="px-3 py-2 text-left w-16">
          <button onClick={() => window.confirm(`إلغاء تخصيص "${ov.item_name}"؟`) && remove.mutate()}
            className="text-xs text-red-500 hover:text-red-700 px-2 py-1">🗑️</button>
        </td>
      )}
    </tr>
  )
}

function OverridesTab({ zones, branchParam, purpose, canEdit, showToast }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [newItem, setNewItem] = useState(null)   // from ItemSearchInput
  const [newZone, setNewZone] = useState('')
  const [newTag, setNewTag]   = useState('')

  const { data: overrides = [] } = useQuery({
    queryKey: ['pick-overrides', branchParam, purpose, search],
    queryFn: () => pickZonesApi.listOverrides({ q: search, branch: branchParam, purpose })
      .then(r => r.data.results || r.data),
  })

  const create = useMutation({
    mutationFn: () => pickZonesApi.createOverride({
      item_code: newItem.softech_id, zone: Number(newZone), tag: newTag.trim(),
      branch: branchBody(branchParam), purpose,
    }),
    onSuccess: () => {
      qc.invalidateQueries(['pick-overrides'])
      qc.invalidateQueries(['pick-uncategorized'])
      qc.invalidateQueries(['pick-zones'])
      setNewItem(null); setNewZone(''); setNewTag('')
      showToast('✅ أُضيف التخصيص')
    },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في الإضافة')}`),
  })

  return (
    <div>
      {canEdit && (
        <div className="card mb-4">
          <div className="font-bold text-gray-800 text-sm mb-2">➕ تخصيص صنف لمنطقة</div>
          <div className="flex flex-wrap gap-2 items-center">
            <div className="flex-1 min-w-64">
              {newItem ? (
                <div className="flex items-center gap-2 bg-brand-50 rounded-xl px-3 py-2 text-sm">
                  <span className="font-semibold flex-1">{newItem.name}</span>
                  <span className="font-mono text-xs text-gray-500">{newItem.softech_id}</span>
                  <button onClick={() => setNewItem(null)} className="text-gray-400 hover:text-gray-700">✕</button>
                </div>
              ) : (
                <ItemSearchInput onSelect={it => setNewItem(it)} placeholder="ابحث عن الصنف..." />
              )}
            </div>
            <select className="input-field text-sm w-44" value={newZone}
              onChange={e => setNewZone(e.target.value)}>
              <option value="">اختر منطقة...</option>
              {zones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
            <input className="input-field text-sm w-36" placeholder="وسم/رف (اختياري)"
              value={newTag} onChange={e => setNewTag(e.target.value)} />
            <button onClick={() => create.mutate()}
              disabled={!newItem || !newZone || create.isPending}
              className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white font-bold px-4 py-2 rounded-lg disabled:opacity-40">
              إضافة
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 mb-3">
        <input className="input-field text-sm w-72" placeholder="ابحث بالاسم أو الكود أو الوسم..."
          value={q}
          onChange={e => setQ(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && setSearch(q.trim())} />
        <button onClick={() => setSearch(q.trim())} className="btn-secondary text-xs px-3 py-1.5">بحث</button>
        <span className="text-xs text-gray-400">{toLatin(overrides.length)} تخصيص في هذا الإعداد</span>
      </div>

      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-24">الكود</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500">اسم الصنف</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-44">المنطقة</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-40">وسم/رف</th>
              <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-500 w-28">بواسطة</th>
              {canEdit && <th className="px-3 py-2.5 w-16" />}
            </tr>
          </thead>
          <tbody>
            {overrides.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-gray-400 text-sm">
                لا توجد تخصيصات{search && ' مطابقة للبحث'} في هذا الإعداد
              </td></tr>
            ) : overrides.map(ov => (
              <OverrideRow key={ov.id} ov={ov} zones={zones}
                canEdit={canEdit} showToast={showToast} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const TABS = [
  { key: 'zones',         label: '📍 المناطق' },
  { key: 'rules',         label: '📐 القواعد' },
  { key: 'uncategorized', label: '❓ غير مصنف' },
  { key: 'overrides',     label: '🏷️ تخصيصات الأصناف' },
]

export default function PickZonesPage() {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const canEdit = user?.role === 'admin' || user?.role === 'purchasing'
  const [tab, setTab] = useState('zones')
  const [toast, setToast] = useState('')
  // '' = the default config; otherwise a branch id (string from the select)
  const [branchParam, setBranchParam] = useState('')
  // 'picking' (مسار مخزن المصدر) or 'stocking' (أرفف الفرع — أيضاً للجرد)
  const [purpose, setPurpose] = useState('picking')

  function showToast(msg) {
    setToast(msg)
    setTimeout(() => setToast(''), 4000)
  }

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
    staleTime: 300_000,
  })

  const { data: zones = [], isLoading } = useQuery({
    queryKey: ['pick-zones', branchParam, purpose],
    queryFn: () => pickZonesApi.listZones({ branch: branchParam, purpose })
      .then(r => r.data.results || r.data),
  })
  const activeZones = zones.filter(z => z.is_active)

  const copyDefaults = useMutation({
    mutationFn: () => pickZonesApi.copyDefaults(
      branchParam === '' ? null : Number(branchParam), purpose),
    onSuccess: (r) => {
      qc.invalidateQueries(['pick-zones'])
      qc.invalidateQueries(['pick-rules'])
      showToast(`✅ نُسخ الإعداد المطبق حالياً (${r.data.zones_created} منطقة، ${r.data.rules_created} قاعدة)`)
    },
    onError: (e) => showToast(`❌ ${errMsg(e, 'خطأ في النسخ')}`),
  })

  // empty config → offer bootstrap-copy, except the default picking config
  // (that one is seeded and should never be empty in practice)
  const configEmpty = !isLoading && zones.length === 0
    && !(branchParam === '' && purpose === 'picking')

  return (
    <div className="min-h-full bg-gray-50 p-6" dir="rtl">
      {toast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 bg-gray-900 text-white px-6 py-3 rounded-xl shadow-xl text-sm font-semibold">
          {toast}
        </div>
      )}

      <div className="flex items-start gap-3 mb-4 flex-wrap">
        <div className="flex-1 min-w-72">
          <h1 className="text-xl font-black text-gray-900">مناطق التجميع — ورقة التجميع</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            تحكم كامل في تصنيف أصناف أذونات الصرف إلى مناطق المخزن: المناطق ومسارها،
            القواعد (كلمات الاسم أو أعمدة جدول الأصناف) وترتيبها، حد الغوالي، الثلاجة،
            وتخصيصات الأصناف — لكل مخزن إعداده الخاص
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Purpose: picking (source warehouse walk) vs stocking (branch shelves) */}
          <div className="flex rounded-xl border border-gray-200 overflow-hidden">
            {PURPOSES.map(p => (
              <button
                key={p.value}
                onClick={() => setPurpose(p.value)}
                title={p.hint}
                className={`text-xs font-bold px-3 py-2 transition-colors ${
                  purpose === p.value
                    ? (p.value === 'picking' ? 'bg-brand-600 text-white' : 'bg-teal-600 text-white')
                    : 'bg-white text-gray-500 hover:bg-gray-50'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <label className="text-xs text-gray-500 font-semibold">الموقع:</label>
          <select
            className="input-field text-sm w-52"
            value={branchParam}
            onChange={e => setBranchParam(e.target.value)}
            title="كل موقع يمكن أن يملك مناطقه وقواعده الخاصة لكل غرض — والمواقع بلا إعداد تتبع الافتراضي"
          >
            <option value="">🏠 الإعداد الافتراضي (عام)</option>
            {branches.map(b => (
              <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
            ))}
          </select>
        </div>
        {!canEdit && (
          <span className="text-[11px] bg-amber-50 text-amber-700 px-3 py-1.5 rounded-full font-semibold">
            👁️ عرض فقط — التعديل للإدارة والمشتريات
          </span>
        )}
      </div>

      {configEmpty && (
        <div className="mb-4 bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap">
          <span className="text-sm text-blue-800">
            {purpose === 'stocking' ? (
              <>🗄️ لا يوجد إعداد ترصيص هنا — أوراق الترصيص والجرد تستخدم حالياً
                <b> سلسلة الرجوع</b> (ترصيص افتراضي ← تجميع الموقع ← تجميع افتراضي).
                لبناء ترتيب أرفف خاص، انسخ الإعداد المطبق كنقطة بداية ثم عدِّل بحرّية.</>
            ) : (
              <>🏠 هذا الموقع لا يملك إعداد تجميع خاصاً — التصدير منه يستخدم
                <b> الإعداد الافتراضي</b> حالياً. انسخه كنقطة بداية ثم عدِّل بحرّية.</>
            )}
          </span>
          {canEdit && (
            <button
              onClick={() => copyDefaults.mutate()}
              disabled={copyDefaults.isPending}
              className="text-xs bg-blue-600 hover:bg-blue-700 text-white font-bold px-4 py-2 rounded-lg disabled:opacity-50"
            >
              {copyDefaults.isPending ? 'جارٍ النسخ...' : '📋 نسخ الإعداد المطبق حالياً كنقطة بداية'}
            </button>
          )}
        </div>
      )}

      <div className="flex border-b border-gray-200 gap-5 mb-4">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`pb-2.5 text-sm font-semibold border-b-2 transition-colors ${
              tab === t.key
                ? 'border-brand-600 text-brand-700'
                : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          {[1, 2, 3, 4, 5].map(i => <div key={i} className="h-12 bg-gray-100 rounded-xl" />)}
        </div>
      ) : (
        <>
          {tab === 'zones'         && <ZonesTab zones={zones} branchParam={branchParam} purpose={purpose} canEdit={canEdit} showToast={showToast} />}
          {tab === 'rules'         && <RulesTab zones={activeZones} branchParam={branchParam} purpose={purpose} canEdit={canEdit} showToast={showToast} />}
          {tab === 'uncategorized' && <UncategorizedTab zones={activeZones} branchParam={branchParam} purpose={purpose} canEdit={canEdit} showToast={showToast} />}
          {tab === 'overrides'     && <OverridesTab zones={activeZones} branchParam={branchParam} purpose={purpose} canEdit={canEdit} showToast={showToast} />}
        </>
      )}
    </div>
  )
}
