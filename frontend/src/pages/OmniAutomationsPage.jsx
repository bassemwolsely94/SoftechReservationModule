/**
 * OmniAutomationsPage.jsx — CEP Phase 4 (doc 15)
 *
 * No-code automation rules: trigger → conditions → actions. Admin/supervisor.
 * The condition/action editors are JSON-schema-lite forms over the engine's
 * documented keys (apps/omni/automation.py).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { omniApi } from '../api/client'

const TRIGGERS = [
  { v: 'message_in', l: 'رسالة واردة' },
  { v: 'call', l: 'مكالمة' },
  { v: 'call_missed', l: 'مكالمة فائتة' },
  { v: 'erp_reservation', l: 'حجز' },
  { v: 'ai_insight', l: 'تحليل ذكي' },
]

const ACTION_TYPES = [
  { v: 'set_priority', l: 'ضبط الأولوية', param: 'priority', placeholder: 'urgent / high / normal' },
  { v: 'set_status', l: 'ضبط الحالة', param: 'status', placeholder: 'pending / resolved' },
  { v: 'add_tag', l: 'إضافة وسم', param: 'tag', placeholder: 'شكوى' },
  { v: 'assign_role', l: 'إسناد لدور', param: 'role', placeholder: 'supervisor' },
  { v: 'notify_role', l: 'إشعار دور', param: 'role', placeholder: 'supervisor', extra: 'text' },
  { v: 'add_note', l: 'إضافة ملاحظة', param: 'text', placeholder: 'نص الملاحظة' },
  { v: 'auto_reply', l: 'رد آلي', param: 'text', placeholder: 'شكراً لتواصلك، سنرد فوراً' },
]

const TRIGGER_LABEL = Object.fromEntries(TRIGGERS.map(t => [t.v, t.l]))

function RuleModal({ rule, onClose }) {
  const isEdit = Boolean(rule?.id)
  const [name, setName] = useState(rule?.name || '')
  const [trigger, setTrigger] = useState(rule?.trigger || 'message_in')
  const [isActive, setIsActive] = useState(rule?.is_active ?? true)
  const [keywords, setKeywords] = useState((rule?.conditions?.text_contains || []).join('، '))
  const [vipOnly, setVipOnly] = useState(Boolean(rule?.conditions?.customer_vip))
  const [channel, setChannel] = useState(rule?.conditions?.channel || '')
  const [actions, setActions] = useState(
    rule?.actions?.length ? rule.actions : [{ type: 'set_priority', priority: 'high' }])
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: () => {
      const conditions = {}
      if (keywords.trim()) {
        conditions.text_contains = keywords.split(/[،,]/).map(s => s.trim()).filter(Boolean)
      }
      if (vipOnly) conditions.customer_vip = true
      if (channel) conditions.channel = channel
      const data = { name, trigger, is_active: isActive, conditions, actions }
      return isEdit ? omniApi.updateAutomation(rule.id, data) : omniApi.createAutomation(data)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['omni-automations'] })
      onClose()
    },
  })

  const setAction = (i, patch) =>
    setActions(a => a.map((x, j) => j === i ? { ...x, ...patch } : x))
  const addAction = () => setActions(a => [...a, { type: 'add_tag', tag: '' }])
  const removeAction = (i) => setActions(a => a.filter((_, j) => j !== i))

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" dir="rtl"
         onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-5 space-y-3 max-h-[90vh] overflow-y-auto"
           onClick={e => e.stopPropagation()}>
        <h2 className="font-bold text-gray-800">{isEdit ? 'تعديل قاعدة' : 'قاعدة أتمتة جديدة'}</h2>

        <input value={name} onChange={e => setName(e.target.value)}
               placeholder="اسم القاعدة"
               className="w-full border border-gray-200 rounded px-3 py-2 text-sm" />

        <label className="block text-xs text-gray-500">
          عند حدوث
          <select value={trigger} onChange={e => setTrigger(e.target.value)}
                  className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm mt-1">
            {TRIGGERS.map(t => <option key={t.v} value={t.v}>{t.l}</option>)}
          </select>
        </label>

        {/* Conditions */}
        <div className="bg-gray-50 rounded p-3 space-y-2">
          <p className="text-xs font-bold text-gray-500">الشروط (كلها يجب أن تتحقق)</p>
          <input value={keywords} onChange={e => setKeywords(e.target.value)}
                 placeholder="كلمات مفتاحية في النص (افصل بفاصلة)"
                 className="w-full border border-gray-200 rounded px-2 py-1.5 text-sm" />
          <div className="flex items-center gap-3 text-xs text-gray-600">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={vipOnly} onChange={e => setVipOnly(e.target.checked)} />
              عملاء VIP فقط
            </label>
            <select value={channel} onChange={e => setChannel(e.target.value)}
                    className="border border-gray-200 rounded px-2 py-1 text-xs">
              <option value="">أي قناة</option>
              <option value="whatsapp">واتساب</option>
              <option value="voice">مكالمات</option>
              <option value="messenger">ماسنجر</option>
              <option value="instagram">إنستجرام</option>
              <option value="telegram">تيليجرام</option>
            </select>
          </div>
        </div>

        {/* Actions */}
        <div className="bg-indigo-50/50 rounded p-3 space-y-2">
          <p className="text-xs font-bold text-gray-500">الإجراءات (بالترتيب)</p>
          {actions.map((a, i) => {
            const meta = ACTION_TYPES.find(t => t.v === a.type) || ACTION_TYPES[0]
            return (
              <div key={i} className="flex items-center gap-1.5">
                <select value={a.type}
                        onChange={e => setAction(i, { type: e.target.value })}
                        className="border border-gray-200 rounded px-1.5 py-1 text-xs">
                  {ACTION_TYPES.map(t => <option key={t.v} value={t.v}>{t.l}</option>)}
                </select>
                <input value={a[meta.param] || ''}
                       onChange={e => setAction(i, { [meta.param]: e.target.value })}
                       placeholder={meta.placeholder}
                       className="flex-1 border border-gray-200 rounded px-2 py-1 text-xs" />
                {meta.extra && (
                  <input value={a[meta.extra] || ''}
                         onChange={e => setAction(i, { [meta.extra]: e.target.value })}
                         placeholder="نص الإشعار"
                         className="flex-1 border border-gray-200 rounded px-2 py-1 text-xs" />
                )}
                <button onClick={() => removeAction(i)} className="text-red-400 text-sm">✕</button>
              </div>
            )
          })}
          <button onClick={addAction} className="text-xs text-indigo-600">+ إجراء</button>
        </div>

        <label className="flex items-center gap-1.5 text-sm text-gray-600">
          <input type="checkbox" checked={isActive} onChange={e => setIsActive(e.target.checked)} />
          مفعّلة
        </label>

        {save.isError && <p className="text-red-500 text-xs">فشل الحفظ</p>}

        <div className="flex gap-2 pt-1">
          <button onClick={() => save.mutate()} disabled={!name.trim() || save.isPending}
                  className="flex-1 bg-indigo-600 text-white rounded px-3 py-2 text-sm disabled:opacity-50">
            {save.isPending ? 'جاري الحفظ...' : 'حفظ'}
          </button>
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500">إلغاء</button>
        </div>
      </div>
    </div>
  )
}

export default function OmniAutomationsPage() {
  const [modal, setModal] = useState(null)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['omni-automations'],
    queryFn: () => omniApi.automations().then(r => r.data),
  })

  const toggle = useMutation({
    mutationFn: ({ id, is_active }) => omniApi.updateAutomation(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['omni-automations'] }),
  })
  const del = useMutation({
    mutationFn: (id) => omniApi.deleteAutomation(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['omni-automations'] }),
  })

  const rules = data?.results || data || []

  return (
    <div className="p-6 max-w-4xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-800">⚙️ قواعد الأتمتة</h1>
          <p className="text-sm text-gray-500 mt-0.5">{rules.length} قاعدة</p>
        </div>
        <button onClick={() => setModal({})}
                className="bg-indigo-600 text-white rounded-lg px-4 py-2 text-sm">
          + قاعدة جديدة
        </button>
      </div>

      {isLoading ? (
        <p className="text-center text-gray-400 py-16">جاري التحميل...</p>
      ) : rules.length === 0 ? (
        <div className="text-center text-gray-400 py-16">
          <p className="text-4xl mb-2">⚙️</p>
          <p>لا توجد قواعد — أنشئ أول قاعدة أتمتة</p>
        </div>
      ) : (
        <div className="space-y-2">
          {rules.map(rule => (
            <div key={rule.id}
                 className="bg-white rounded-lg border border-gray-200 p-3 flex items-center justify-between">
              <div className="min-w-0">
                <p className="font-medium text-gray-800">
                  {rule.name}
                  {!rule.is_active && <span className="mr-2 text-xs text-gray-400">(معطّلة)</span>}
                </p>
                <p className="text-xs text-gray-500 mt-0.5">
                  عند: {TRIGGER_LABEL[rule.trigger] || rule.trigger}
                  {' · '}{(rule.actions || []).length} إجراء
                  {' · '}نُفّذت {rule.run_count} مرة
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => toggle.mutate({ id: rule.id, is_active: !rule.is_active })}
                        className={`text-xs px-2 py-1 rounded-full
                          ${rule.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                  {rule.is_active ? 'مفعّلة' : 'معطّلة'}
                </button>
                <button onClick={() => setModal(rule)} className="text-xs text-gray-500 hover:text-indigo-600">✏️</button>
                <button onClick={() => { if (confirm('حذف القاعدة؟')) del.mutate(rule.id) }}
                        className="text-xs text-gray-400 hover:text-red-500">🗑️</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal !== null && (
        <RuleModal rule={modal.id ? modal : null} onClose={() => setModal(null)} />
      )}
    </div>
  )
}
