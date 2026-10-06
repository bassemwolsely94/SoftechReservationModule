/**
 * FollowUpsPage.jsx  —  /followups
 *
 * Full chronic-medication follow-up module.
 * Connects: Catalog (full product), Customers (CRM data), FBT cross-sell,
 *           WhatsApp pre-filled messages, Call Center log-call, Sales Channels.
 *
 * API shape (from backend serializers):
 *   task.customer = {
 *     id, name, phone, whatsapp_phone,
 *     phone_available,       ← true if a real phone exists in DB
 *     can_see_phone,         ← false → phone is masked ('●●●●●●●●●●')
 *     source,                ← 'customer' | 'local_customer' | 'phcode_only'
 *     channel_code, channel_label, segment, churn_segment, churn_score, ltv
 *   }
 *   task.product  = { name, indication, dosage_form, pack_size_label, medicine_type,
 *                     active_ingredients, pack_price, avg_daily_usage, expected_duration_days }
 *   task.refill   = { last_sale_date, due_date, days_until_due, days_overdue, is_overdue }
 *   task.complementary = [{ id, name, indication, pack_price }]
 *   task.call_history  = [{ id, direction, purpose, status, summary, created_at }]
 *
 * Permission rules (enforced server-side + mirrored in UI):
 *   - Phone visible: admin | call_center | supervisor | can_see_customer_phone=true
 *   - WhatsApp send button: only shown when phone is actually available + user can see it
 */
import { useState, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { followupsApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { format, parseISO } from 'date-fns'
import { ar } from 'date-fns/locale'
import RefreshButton from '../components/RefreshButton'
import ModuleNotificationBell from '../components/ModuleNotificationBell'
import CanDo from '../components/CanDo'

// ─────────────────────────────────────────────
//  Constants / config
// ─────────────────────────────────────────────
const STATUS_CFG = {
  pending:     { label: 'معلق',           bg: '#fffbeb', text: '#92400e', dot: '#f59e0b', border: '#fcd34d' },
  called:      { label: 'تم الاتصال',    bg: '#eff6ff', text: '#1e40af', dot: '#3b82f6', border: '#93c5fd' },
  done:        { label: 'مكتمل',          bg: '#f0fdf4', text: '#166534', dot: '#10b981', border: '#6ee7b7' },
  missed:      { label: 'فائت',           bg: '#fef2f2', text: '#991b1b', dot: '#ef4444', border: '#fca5a5' },
  auto_closed: { label: 'أُغلق تلقائياً', bg: '#f5f3ff', text: '#5b21b6', dot: '#8b5cf6', border: '#c4b5fd' },
  cancelled:   { label: 'ملغي',           bg: '#f9fafb', text: '#9ca3af', dot: '#9ca3af', border: '#e5e7eb' },
}

// Channel codes come from stktransm.ptclassifcode (invoice-level, SOFTECH authoritative).
// Do NOT use personsdata.ptclassifcode — it is blank for all customers in this dataset.
const CHANNEL_CFG = {
  '91': { label: 'كاش / مشي',      color: '#0ea5e9', bg: '#f0f9ff', favoured: true,  icon: '🚶' },
  '90': { label: 'توصيل',          color: '#8b5cf6', bg: '#f5f3ff', favoured: true,  icon: '🚚' },
  '13': { label: 'عميل دائم',     color: '#10b981', bg: '#f0fdf4', favoured: true,  icon: '⭐' },
  '10': { label: 'بيع عام',        color: '#06b6d4', bg: '#ecfeff', favoured: true,  icon: '🏪' },
  '11': { label: 'شركات',          color: '#6366f1', bg: '#eef2ff', favoured: false, icon: '🏢' },
  '12': { label: 'جملة',           color: '#a855f7', bg: '#faf5ff', favoured: false, icon: '📦' },
  '30': { label: 'أخرى',           color: '#94a3b8', bg: '#f8fafc', favoured: false, icon: '📋' },
  '15': { label: 'تأمين',          color: '#6b7280', bg: '#f9fafb', favoured: false, icon: '🏥' },
  '16': { label: 'تأمين طبي',      color: '#6b7280', bg: '#f9fafb', favoured: false, icon: '🏥' },
  '17': { label: 'تأمين تكميلي',   color: '#6b7280', bg: '#f9fafb', favoured: false, icon: '🏥' },
}

// Fallback for unknown codes
function getChannelCfg(code) {
  return CHANNEL_CFG[code] || {
    label: `قناة ${code || '—'}`, color: '#9ca3af', bg: '#f3f4f6', favoured: false, icon: '❓',
  }
}

const SEGMENT_COLORS = {
  vip:     { bg: '#fef9c3', text: '#713f12', label: 'VIP' },
  loyal:   { bg: '#dcfce7', text: '#14532d', label: 'وفي' },
  regular: { bg: '#f0f9ff', text: '#0c4a6e', label: 'عادي' },
  at_risk: { bg: '#fff7ed', text: '#7c2d12', label: 'في خطر' },
  dormant: { bg: '#f3f4f6', text: '#374151', label: 'خامل' },
  churned: { bg: '#fef2f2', text: '#7f1d1d', label: 'مفقود' },
}

const CHURN_COLORS = {
  low:      '#10b981',
  medium:   '#f59e0b',
  high:     '#ef4444',
  critical: '#dc2626',
}

// ─────────────────────────────────────────────
//  Small reusable components
// ─────────────────────────────────────────────
function StatusBadge({ status, size = 'sm' }) {
  const s = STATUS_CFG[status] || STATUS_CFG.pending
  const sz = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-semibold ${sz}`}
      style={{ background: s.bg, color: s.text, border: `1px solid ${s.border}` }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.dot }} />
      {s.label}
    </span>
  )
}

function ChannelBadge({ code, size = 'sm' }) {
  if (!code) return null
  const cfg = getChannelCfg(code)
  const sz = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'
  return (
    <span className={`inline-flex items-center gap-1 rounded-full font-semibold ${sz}`}
      style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}30` }}>
      {cfg.icon} {cfg.label}
    </span>
  )
}

function SegmentBadge({ segment }) {
  if (!segment) return null
  const s = SEGMENT_COLORS[segment] || { bg: '#f3f4f6', text: '#374151', label: segment }
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-bold"
      style={{ background: s.bg, color: s.text }}>
      {s.label}
    </span>
  )
}

function ChurnBar({ score, segment }) {
  const color = CHURN_COLORS[segment] || '#10b981'
  const pct   = Math.round(score || 0)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-xs font-mono" style={{ color }}>{pct}%</span>
    </div>
  )
}

function OverdueBadge({ days }) {
  if (!days || days <= 0) return null
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-700">
      ⚠ متأخر {days} يوم
    </span>
  )
}

function DaysUntilBadge({ days }) {
  if (days === null || days === undefined) return null
  if (days < 0) return <OverdueBadge days={-days} />
  if (days === 0) return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-orange-100 text-orange-700">🔔 اليوم</span>
  if (days <= 3)  return <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-700">⏰ {days} أيام</span>
  return <span className="text-xs text-gray-400">{days} يوم</span>
}

// ─────────────────────────────────────────────
//  Outcome preset data (shared by TaskDrawer + QuickActionModal + batch bar)
// ─────────────────────────────────────────────
const OUTCOME_BUCKETS = [
  {
    id: 'done',   label: '✅ اشترى / أكّد',  color: 'green',
    presets: ['confirmed_visit','confirmed_delivery','requested_delivery',
              'bought_elsewhere','substitute_found','doctor_changed'],
  },
  {
    id: 'called', label: '📞 تواصلت',         color: 'blue',
    presets: ['call_later','item_unavailable','hospitalised'],
  },
  {
    id: 'missed', label: '❌ لا رد / مشكلة',  color: 'red',
    presets: ['no_answer_week','wrong_number','refused'],
  },
]

const LOCAL_PRESETS = [
  { id: 'confirmed_visit',    label: '✅ أكّد الحضور للفرع',       result_status: 'done',   side_action: '' },
  { id: 'confirmed_delivery', label: '🚚 تأكيد طلب توصيل',          result_status: 'done',   side_action: 'create_demand' },
  { id: 'requested_delivery', label: '🚚 طلب توصيل (جديد)',          result_status: 'done',   side_action: 'create_demand' },
  { id: 'call_later',         label: '📅 سيتصل لاحقاً',             result_status: 'called', side_action: '' },
  { id: 'item_unavailable',   label: '❌ الصنف غير متوفر',           result_status: 'called', side_action: 'create_demand' },
  { id: 'bought_elsewhere',   label: '🏪 اشترى من مكان آخر',         result_status: 'done',   side_action: '' },
  { id: 'substitute_found',   label: '💊 اشترى بديلاً',             result_status: 'done',   side_action: '' },
  { id: 'doctor_changed',     label: '🏥 طبيبه غيّر الدواء',        result_status: 'done',   side_action: '' },
  { id: 'no_answer_week',     label: '🔇 لا يرد منذ أسبوع',         result_status: 'missed', side_action: '' },
  { id: 'wrong_number',       label: '📵 الرقم خاطئ / غير فعّال',   result_status: 'missed', side_action: 'flag_phone' },
  { id: 'hospitalised',       label: '🏥 متوجد بالمستشفى',           result_status: 'called', side_action: '' },
  { id: 'refused',            label: '🚫 رفض',                      result_status: 'missed', side_action: '' },
]

const STATUS_COLOR_MAP = { done: 'green', called: 'blue', missed: 'red' }

// ─────────────────────────────────────────────
//  Advanced Filter Panel
// ─────────────────────────────────────────────
function FilterPanel({ filters, setFilters, meta, branches }) {
  const [open, setOpen] = useState(false)

  const activeCount = [
    filters.sales_channel?.length,
    filters.favoured_only,
    filters.indication,
    filters.medicine_type,
    filters.segment,
    filters.churn_segment,
    filters.item_search,
    filters.customer_search,
    filters.due_after,
    filters.due_before,
    filters.overdue_only,
    filters.branch,
  ].filter(Boolean).length

  const set = (key, val) => setFilters(p => ({ ...p, [key]: val }))

  const toggleChannel = (code) => {
    const cur = filters.sales_channel || []
    set('sales_channel', cur.includes(code) ? cur.filter(c => c !== code) : [...cur, code])
  }

  const reset = () => setFilters(p => ({
    status: p.status, ordering: p.ordering, by_priority: p.by_priority,
  }))

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      {/* Toggle bar */}
      <button
        onClick={() => setOpen(p => !p)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50 transition-colors">
        <span className="flex items-center gap-2">
          <span>🔍</span>
          <span>فلاتر متقدمة</span>
          {activeCount > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs bg-brand-100 text-brand-700 font-bold">
              {activeCount} نشط
            </span>
          )}
        </span>
        <span className="text-gray-400">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 px-4 py-4 space-y-4">
          {/* Row 1: Sales channels */}
          <div>
            <div className="text-xs font-bold text-gray-500 mb-2">📡 قناة البيع</div>
            <div className="flex flex-wrap gap-2">
              {(meta?.channels?.length ? meta.channels : Object.entries(CHANNEL_CFG).map(([code, c]) => ({ code, label: c.label, favoured: c.favoured }))).map(ch => {
                const cfg    = getChannelCfg(ch.code)
                const active = (filters.sales_channel || []).includes(ch.code)
                return (
                  <button key={ch.code}
                    onClick={() => toggleChannel(ch.code)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                      active ? 'ring-2 ring-offset-1' : 'opacity-60 hover:opacity-90'
                    }`}
                    style={{
                      background:  cfg.bg,
                      color:       cfg.color,
                      borderColor: active ? cfg.color : `${cfg.color}40`,
                    }}>
                    {cfg.icon} {ch.label || cfg.label}
                    {!ch.favoured && <span className="opacity-50 text-[10px]">(أقل أولوية)</span>}
                  </button>
                )
              })}
              <button
                onClick={() => set('favoured_only', !filters.favoured_only)}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                  filters.favoured_only
                    ? 'bg-emerald-100 text-emerald-700 border-emerald-400 ring-2 ring-offset-1 ring-emerald-400'
                    : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100'
                }`}>
                ⭐ المفضّلة فقط
              </button>
            </div>
          </div>

          {/* Row 2: Item search + customer search */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">💊 بحث صنف</label>
              <input type="text" className="input-field text-sm"
                placeholder="اسم الدواء، مادة فعّالة، كود..."
                value={filters.item_search || ''}
                onChange={e => set('item_search', e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">👤 بحث عميل</label>
              <input type="text" className="input-field text-sm"
                placeholder="اسم، موبايل، واتساب..."
                value={filters.customer_search || ''}
                onChange={e => set('customer_search', e.target.value)} />
            </div>
          </div>

          {/* Row 3: Indication + Medicine type */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">🏥 التشخيص / الاستخدام</label>
              <select className="input-field text-sm"
                value={filters.indication || ''}
                onChange={e => set('indication', e.target.value)}>
                <option value="">كل التشخيصات</option>
                {(meta?.indications || []).map(i => (
                  <option key={i.code} value={i.label}>{i.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">💉 نوع الدواء</label>
              <select className="input-field text-sm"
                value={filters.medicine_type || ''}
                onChange={e => set('medicine_type', e.target.value)}>
                <option value="">كل الأنواع</option>
                {(meta?.medicine_types || []).map(m => (
                  <option key={m.code} value={m.code}>{m.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Row 4: Customer segment + churn + branch */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">📊 شريحة العميل</label>
              <select className="input-field text-sm"
                value={filters.segment || ''}
                onChange={e => set('segment', e.target.value)}>
                <option value="">كل الشرائح</option>
                {(meta?.segments || []).map(s => (
                  <option key={s.code} value={s.code}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">⚠ خطر الانقطاع</label>
              <select className="input-field text-sm"
                value={filters.churn_segment || ''}
                onChange={e => set('churn_segment', e.target.value)}>
                <option value="">كل المستويات</option>
                {(meta?.churn_segments || []).map(s => (
                  <option key={s.code} value={s.code}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">🏪 الفرع</label>
              <select className="input-field text-sm"
                value={filters.branch || ''}
                onChange={e => set('branch', e.target.value)}>
                <option value="">كل الفروع</option>
                {(branches || []).map(b => (
                  <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Row 5: Date range + overdue */}
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">📅 الاستحقاق من</label>
              <input type="date" className="input-field text-sm"
                value={filters.due_after || ''}
                onChange={e => set('due_after', e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-bold text-gray-500 block mb-1">📅 الاستحقاق إلى</label>
              <input type="date" className="input-field text-sm"
                value={filters.due_before || ''}
                onChange={e => set('due_before', e.target.value)} />
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none pb-1">
              <input type="checkbox" className="w-4 h-4 accent-red-500"
                checked={!!filters.overdue_only}
                onChange={e => set('overdue_only', e.target.checked)} />
              <span className="font-semibold text-red-700">المتأخرة فقط</span>
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none pb-1">
              <input type="checkbox" className="w-4 h-4 accent-brand-600"
                checked={!!filters.by_priority}
                onChange={e => set('by_priority', e.target.checked)} />
              <span className="font-semibold text-gray-700">ترتيب حسب الأولوية</span>
            </label>
          </div>

          {activeCount > 0 && (
            <button onClick={reset}
              className="text-xs text-gray-400 hover:text-red-600 underline mt-1">
              مسح كل الفلاتر
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────
//  Task Card (rich)
// ─────────────────────────────────────────────
// Phone display component — respects server-side masking
function PhoneDisplay({ phone, canSeePhone, className = '' }) {
  if (!phone) return null
  const isMasked = !canSeePhone || phone === '●●●●●●●●●●'
  return (
    <span
      className={`font-mono text-xs select-all ${isMasked ? 'tracking-widest text-gray-300' : 'text-gray-400'} ${className}`}
      dir="ltr"
      title={isMasked ? 'ليس لديك صلاحية رؤية رقم الهاتف' : phone}>
      {isMasked ? '🔒 ●●●●●●●●' : phone}
    </span>
  )
}

function PinButton({ task, onPinToggle }) {
  const [loading, setLoading] = useState(false)
  const isPinned = task.is_pinned

  const toggle = async (e) => {
    e.stopPropagation()
    setLoading(true)
    try {
      if (isPinned) {
        await followupsApi.unpin(task.id)
      } else {
        await followupsApi.pin(task.id)
      }
      onPinToggle()
    } catch { } finally { setLoading(false) }
  }

  return (
    <button
      onClick={toggle}
      disabled={loading}
      title={isPinned ? 'إلغاء التثبيت' : 'تثبيت للمتابعة الشخصية'}
      className={`text-lg p-1 rounded-lg transition-all ${
        isPinned
          ? 'text-amber-500 bg-amber-50 hover:bg-amber-100'
          : 'text-gray-300 hover:text-amber-400 hover:bg-amber-50'
      } disabled:opacity-50`}>
      📌
    </button>
  )
}

function TaskCard({ task, onSelect, onQuickAction, onPinToggle, isSelected, onSelect2 }) {
  const c   = task.customer  || {}
  const p   = task.product   || {}
  const r   = task.refill    || {}
  const cfg = getChannelCfg(c.channel_code || task.sales_channel)
  const isOverdue    = r.is_overdue || r.days_overdue > 0
  const canSeePhone  = c.can_see_phone !== false
  const hasPhone     = c.phone_available && canSeePhone
  const waPhone      = c.whatsapp_phone || c.phone
  const waAvailable  = hasPhone && waPhone && waPhone !== '●●●●●●●●●●'
  const priorityPct  = Math.round((task.priority_score || 0) * 100)

  return (
    <div
      className={`bg-white rounded-xl border px-4 py-3.5 flex gap-4 transition-all hover:shadow-md ${
        isSelected
          ? 'border-brand-400 bg-brand-50/30 ring-1 ring-brand-300'
          : isOverdue
            ? 'border-red-200 bg-red-50/40'
            : task.is_pinned
              ? 'border-amber-300 bg-amber-50/30'
              : 'border-gray-100 hover:border-brand-200'
      } ${task.phone_invalid ? 'opacity-60' : ''}`}
      onClick={() => onSelect(task)}>
      {/* Batch select checkbox */}
      <div className="flex-shrink-0 flex items-start pt-0.5" onClick={e => { e.stopPropagation(); onSelect2?.(task.id) }}>
        <input type="checkbox" className="w-4 h-4 accent-brand-600 cursor-pointer"
          checked={!!isSelected} onChange={() => onSelect2?.(task.id)} />
      </div>

      {/* Channel + priority indicator strip */}
      <div className="flex flex-col gap-0.5 flex-shrink-0">
        <div className="w-1 rounded-full flex-1" style={{ background: cfg.color || '#e5e7eb' }} />
        {priorityPct > 60 && (
          <div className="w-1 h-1 rounded-full bg-amber-400 flex-shrink-0"
            title={`أولوية: ${priorityPct}%`} />
        )}
      </div>

      <div className="flex-1 min-w-0 space-y-2">
        {/* Top row: customer name + badges */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`font-bold text-sm ${c.name && c.name !== '—' ? 'text-gray-900' : 'text-gray-400 italic'}`}>
            {c.name || '—'}
          </span>
          {c.source === 'local_customer' && (
            <span className="text-[10px] px-1.5 py-0.5 bg-amber-50 text-amber-600 border border-amber-200 rounded-full">
              PIC
            </span>
          )}
          <PhoneDisplay phone={c.phone} canSeePhone={canSeePhone} />
          <StatusBadge status={task.status} />
          <ChannelBadge code={c.channel_code || task.sales_channel} />
          {c.segment && <SegmentBadge segment={c.segment} />}
          {isOverdue && <OverdueBadge days={r.days_overdue} />}
          {!isOverdue && r.days_until_due <= 3 && <DaysUntilBadge days={r.days_until_due} />}
          {task.assignee_count > 0 ? (
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100"
              title={(task.assignee_names || []).join(' · ')}>
              👥 {task.assignee_count === 1
                ? task.assignee_names?.[0] || task.assigned_to_name
                : `${task.assignee_count} موظفين`}
            </span>
          ) : task.assigned_to_name ? (
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
              👤 {task.assigned_to_name}
            </span>
          ) : null}
          {task.is_pinned && !task.assignee_count && !task.assigned_to_name && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 text-amber-600 border border-amber-200">
              📌 مثبتة
            </span>
          )}
          {task.phone_invalid && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 border border-gray-200">
              📵 رقم خاطئ
            </span>
          )}
          {task.demand_number && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-600 border border-purple-100">
              📋 {task.demand_number}
            </span>
          )}
        </div>

        {/* Product row */}
        <div className="flex items-start gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-brand-700">
              💊 {p.name || '—'}
            </div>
            {p.indication && (
              <div className="text-xs text-gray-500 mt-0.5">🏥 {p.indication}</div>
            )}
            <div className="flex gap-2 mt-0.5">
              {p.dosage_form    && <span className="text-xs text-gray-400">{p.dosage_form}</span>}
              {p.pack_size_label && <span className="text-xs text-gray-400">📦 {p.pack_size_label}</span>}
            </div>
          </div>
          {p.avg_daily_usage && (
            <div className="text-xs bg-amber-50 text-amber-700 rounded-lg px-2 py-1 border border-amber-100 flex-shrink-0">
              {p.avg_daily_usage}/يوم · {p.expected_duration_days} يوم
            </div>
          )}
        </div>

        {/* Refill timing + transaction reference row */}
        <div className="flex items-center gap-3 flex-wrap text-xs text-gray-400">
          {r.last_sale_date && (
            <span>آخر صرف: <strong className="text-gray-600">{r.last_sale_date}</strong></span>
          )}
          {r.due_date && (
            <span>استحقاق: <strong className={isOverdue ? 'text-red-600' : 'text-gray-700'}>{r.due_date}</strong></span>
          )}
          {/* SOFTECH ERP reference */}
          {r.docnumber && (
            <span className="font-mono bg-gray-50 border border-gray-200 rounded px-1.5 py-0.5 text-gray-600 select-all"
              title="رقم المستند في SOFTECH — انسخه للبحث في الـ ERP">
              #{r.docnumber}
            </span>
          )}
          {(r.branch_name || r.softech_branch_code) && (
            <span title={`كود الفرع في ERP: ${r.softech_branch_code}`}>
              📍 {r.branch_name || `فرع ${r.softech_branch_code}`}
            </span>
          )}
          {task.attempts > 0 && <span className="text-orange-600">{task.attempts} محاولة</span>}
          {c.ltv > 0 && (
            <span className="text-emerald-600 font-semibold">LTV: {c.ltv.toLocaleString('en-US')} ج</span>
          )}
        </div>
      </div>

      {/* Right actions */}
      <div className="flex flex-col items-end gap-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
        {/* Pin toggle — always visible */}
        <PinButton task={task} onPinToggle={onPinToggle} />

        {waAvailable ? (
          <button
            onClick={() => onSelect(task)}
            className="text-green-500 hover:text-green-700 text-xl p-1 hover:bg-green-50 rounded-lg transition"
            title="إرسال واتساب">
            💬
          </button>
        ) : c.phone_available && !canSeePhone ? (
          <span className="text-gray-300 text-xl p-1" title="الهاتف محجوب">🔒</span>
        ) : null}

        {['pending', 'called'].includes(task.status) && (
          <button
            onClick={() => onQuickAction(task)}
            className="btn-primary text-xs px-3 py-1.5 whitespace-nowrap">
            تسجيل النتيجة
          </button>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────
//  Feature 6 — CustomerGroupCard
// ─────────────────────────────────────────────
function CustomerGroupCard({ group, onOpenTask, onQuickAction, onMutate }) {
  const [expanded,      setExpanded]      = useState(false)
  const [selectedItems, setSelectedItems] = useState([])   // task IDs to include in WA message
  const [waMsg,         setWaMsg]         = useState('')
  const [waUrl,         setWaUrl]         = useState('')
  const [composing,     setComposing]     = useState(false) // show WA composer panel
  const [building,      setBuilding]      = useState(false)
  const [batchRunning,  setBatchRunning]  = useState(false)

  const c      = group.customer || {}
  const rawTasks = group.tasks  || []
  const stats  = group.stats    || {}
  const cfg    = getChannelCfg(c.channel_code)
  // Phone visibility is determined server-side per customer block — never hardcoded.
  const canSeePhone = c.can_see_phone !== false

  // Deduplicate: same item + same invoice = keep one row (expiry-split artefact from SOFTECH)
  // If same item appears across DIFFERENT invoices, keep all (each is a separate purchase event)
  const tasks = (() => {
    const seen = new Set()
    return rawTasks.filter(task => {
      const itemId   = task.product?.id ?? task.id
      const docnum   = task.refill?.docnumber || 'no-doc'
      const key      = `${itemId}_${docnum}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  })()

  // All active task IDs for this customer
  const activeTaskIds = tasks.filter(t => ['pending','called'].includes(t.status)).map(t => t.id)

  const toggleItem = (id) =>
    setSelectedItems(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const buildMessage = async (includeUpsell = false) => {
    const ids = selectedItems.length > 0 ? selectedItems : activeTaskIds
    if (!ids.length) return
    setBuilding(true)
    try {
      const res = await followupsApi.multiWhatsapp(ids, includeUpsell)
      setWaMsg(res.data.message)
      setWaUrl(res.data.whatsapp_url)
      setComposing(true)
      // Do NOT call onMutate() here — it invalidates followup-grouped which
      // re-renders all group cards and resets the composing state to false.
      // The status update (tasks → 'called') already happened server-side.
      // onMutate() is called when the user explicitly closes the composer.
    } catch (e) {
      alert('فشل: ' + (e?.response?.data?.detail || e.message))
    } finally { setBuilding(false) }
  }

  const closeComposer = () => {
    setComposing(false)
    onMutate()   // refresh group data only AFTER composer is closed
  }

  const handleBatchStatus = async (action) => {
    const ids = selectedItems.length > 0 ? selectedItems : activeTaskIds
    setBatchRunning(true)
    try {
      await followupsApi.bulkAction(ids, action)
      onMutate()
      setSelectedItems([])
    } catch { } finally { setBatchRunning(false) }
  }

  return (
    <div className={`bg-white rounded-2xl border overflow-hidden transition-all ${
      stats.overdue > 0 ? 'border-red-200' : 'border-gray-200'
    }`}>
      {/* ── Customer header ── */}
      <div className="px-4 py-3.5 flex items-center gap-3 cursor-pointer hover:bg-gray-50"
        onClick={() => setExpanded(p => !p)}>
        {/* Channel strip */}
        <div className="w-1.5 self-stretch rounded-full flex-shrink-0"
          style={{ background: cfg.color || '#e5e7eb' }} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`font-bold text-sm ${c.name && c.name !== '—' ? 'text-gray-900' : 'text-gray-400 italic'}`}>
              {c.name || '—'}
            </span>
            <ChannelBadge code={c.channel_code} />
            {c.segment && <SegmentBadge segment={c.segment} />}
            {stats.overdue > 0 && <OverdueBadge days={stats.overdue} />}
            {c.phone_available && canSeePhone && (
              <PhoneDisplay phone={c.phone} canSeePhone />
            )}
          </div>
          <div className="flex items-center gap-2 mt-1 text-xs text-gray-400 flex-wrap">
            <span className="flex items-center gap-1">
              💊 <strong className="text-gray-700">{tasks.length}</strong>
              {tasks.length !== rawTasks.length && (
                <span className="text-gray-400">
                  ({rawTasks.length} قبل الدمج)
                </span>
              )}
            </span>
            {stats.pending > 0 && (
              <span className="text-amber-600 font-semibold">· {stats.pending} معلق</span>
            )}
            {stats.overdue > 0 && (
              <span className="text-red-600 font-bold">· {stats.overdue} متأخر</span>
            )}
            {stats.at_risk_value > 0 && (
              <span className="text-amber-700">
                · ⚠ {stats.at_risk_value.toLocaleString('en-US', { maximumFractionDigits: 0 })} ج
              </span>
            )}
            {c.ltv > 0 && (
              <span className="text-emerald-600">· LTV {c.ltv.toLocaleString('en-US', { maximumFractionDigits: 0 })} ج</span>
            )}
            {c.phcode && <span className="font-mono text-gray-300 mr-1">{c.phcode}</span>}
          </div>
        </div>

        {/* Quick actions header */}
        <div className="flex items-center gap-2 flex-shrink-0" onClick={e => e.stopPropagation()}>
          {/* WA button: if collapsed → expand so user can select items first;
              if already expanded → build message with selection (or all) */}
          {activeTaskIds.length > 0 && c.phone_available && canSeePhone && (
            <button
              disabled={building}
              onClick={() => {
                if (!expanded) {
                  setExpanded(true)
                } else {
                  buildMessage(false)
                }
              }}
              title={expanded ? 'إرسال رسالة واتساب للأدوية المحددة (أو الكل)' : 'فتح القائمة لاختيار الأدوية قبل الإرسال'}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-green-500 text-white hover:bg-green-600 transition-colors disabled:opacity-50">
              {building ? '...' : expanded
                ? (selectedItems.length > 0 ? `💬 واتساب (${selectedItems.length})` : '💬 الكل')
                : '💬 اختر'}
            </button>
          )}
          <span className="text-gray-400 text-xs">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* ── WhatsApp Composer Panel ── */}
      {composing && (
        <div className="border-t border-green-100 bg-green-50/30 px-4 py-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-green-800">💬 رسالة واتساب — {selectedItems.length || activeTaskIds.length} دواء</span>
            <div className="flex gap-2">
              <button onClick={() => buildMessage(true)} disabled={building}
                className="text-xs text-blue-600 hover:underline disabled:opacity-50">
                + إضافة توصيات تكميلية
              </button>
              <button onClick={closeComposer} className="text-xs text-gray-400 hover:text-red-600">✕</button>
            </div>
          </div>
          {/* Editable message bubble */}
          <div className="bg-[#dcf8c6] rounded-2xl rounded-tl-none p-3 text-sm text-gray-800 whitespace-pre-wrap leading-relaxed" dir="rtl">
            {waMsg}
          </div>
          <textarea
            rows={6}
            className="input-field resize-y text-sm leading-relaxed w-full"
            dir="rtl"
            value={waMsg}
            onChange={e => {
              setWaMsg(e.target.value)
              const rawPhone = c.whatsapp_phone || c.phone
              if (rawPhone) {
                const cleaned = normalisePhone(rawPhone)
                setWaUrl(`https://wa.me/${cleaned}?text=${encodeURIComponent(e.target.value)}`)
              }
            }}
          />
          <div className="flex gap-2">
            <a href={waUrl} target="_blank" rel="noopener noreferrer"
              className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-green-500 hover:bg-green-600 text-white font-bold text-sm transition-colors">
              💬 إرسال عبر واتساب
            </a>
            <button onClick={() => navigator.clipboard?.writeText(waMsg)}
              className="px-4 py-2.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm">
              📋 نسخ
            </button>
            <button onClick={closeComposer}
              className="px-4 py-2.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-500 text-sm">
              إغلاق
            </button>
          </div>
        </div>
      )}

      {/* ── Expanded medication list ── */}
      {expanded && (
        <div className="border-t border-gray-100">
          {/* Batch toolbar for this group */}
          <div className="px-4 py-2 bg-gray-50 border-b border-gray-100 flex items-center gap-2 flex-wrap">
            {/* Item selection for WA message */}
            <div className="flex items-center gap-1.5">
              <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer"
                title="حدد أدوية بعينها لتضمينها في رسالة الواتساب — تجاهل هذا الخيار يرسل الرسالة لكل الأدوية النشطة">
                <input type="checkbox" className="w-3.5 h-3.5 accent-brand-600"
                  checked={selectedItems.length === activeTaskIds.length && activeTaskIds.length > 0}
                  onChange={() => setSelectedItems(
                    selectedItems.length === activeTaskIds.length ? [] : [...activeTaskIds]
                  )} />
                <span>تحديد الكل</span>
              </label>
              {selectedItems.length > 0 ? (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-green-100 text-green-700 border border-green-200">
                  {selectedItems.length} للرسالة ✓
                </span>
              ) : (
                <span className="text-[10px] text-gray-400 hidden sm:inline">
                  (حدد لتخصيص الرسالة)
                </span>
              )}
            </div>
            <div className="flex-1" />
            {activeTaskIds.length > 0 && (
              <>
                <button disabled={batchRunning}
                  onClick={() => handleBatchStatus('mark_called')}
                  className="px-2 py-1 text-xs font-semibold rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-50">
                  📞 اتصلت بالكل
                </button>
                <button disabled={batchRunning}
                  onClick={() => handleBatchStatus('mark_done')}
                  className="px-2 py-1 text-xs font-semibold rounded-lg bg-green-50 text-green-700 hover:bg-green-100 disabled:opacity-50">
                  ✅ الكل اشترى
                </button>
              </>
            )}
            {(selectedItems.length > 0 || activeTaskIds.length > 0) && c.phone_available && canSeePhone && (
              <button disabled={building}
                onClick={() => buildMessage(false)}
                className="px-2 py-1 text-xs font-semibold rounded-lg bg-green-100 text-green-700 hover:bg-green-200 disabled:opacity-50 whitespace-nowrap">
                💬 {selectedItems.length > 0 ? `واتساب (${selectedItems.length} دواء)` : 'واتساب الكل'}
              </button>
            )}
          </div>

          {/* Medication rows — clean hierarchy:
               [checkbox · urgency] [drug name + status]   [تسجيل]
                                    [indication · dates]
                                    [#docnum · dosing]       */}
          {tasks.map(task => {
            const p        = task.product || {}
            const r        = task.refill  || {}
            const isActive  = ['pending', 'called'].includes(task.status)
            const isChecked = selectedItems.includes(task.id)
            const isOverdue2 = r.is_overdue || r.days_overdue > 0

            return (
              <div key={task.id}
                className={`flex items-center gap-3 px-4 py-2.5 border-b border-gray-50 last:border-0 transition-colors hover:bg-gray-50/60 cursor-pointer ${
                  isOverdue2 ? 'bg-red-50/30' : ''
                }`}
                onClick={() => onOpenTask(task)}>

                {/* Checkbox — stops propagation so click doesn't open task */}
                <div className="flex-shrink-0" onClick={e => e.stopPropagation()}>
                  <input type="checkbox"
                    className="w-4 h-4 accent-brand-600"
                    checked={isChecked}
                    disabled={!isActive}
                    title="تحديد لتضمينه في رسالة الواتساب"
                    onChange={() => isActive && toggleItem(task.id)} />
                </div>

                {/* Urgency strip + status dot */}
                <div className="flex flex-col items-center gap-1 flex-shrink-0">
                  <div className="w-2 h-2 rounded-full"
                    style={{ background: STATUS_CFG[task.status]?.dot || '#9ca3af' }} />
                  {isOverdue2 && (
                    <div className="w-1 rounded-full bg-red-400 flex-shrink-0" style={{ height: '20px' }} />
                  )}
                </div>

                {/* Main content */}
                <div className="flex-1 min-w-0 space-y-0.5">
                  {/* Row 1: Drug name (full) + item code + urgency + status */}
                  <div className="flex items-start gap-2 flex-wrap">
                    <span className="font-semibold text-sm text-gray-900 leading-snug">
                      {p.name || '—'}
                    </span>
                    {p.softech_id && (
                      <span className="font-mono text-[11px] px-1.5 py-0.5 bg-slate-100 border border-slate-200 text-slate-500 rounded flex-shrink-0 select-all"
                        title="كود الصنف في ERP">
                        {p.softech_id}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-wrap mt-0.5">
                    {isOverdue2
                      ? <OverdueBadge days={r.days_overdue} />
                      : <DaysUntilBadge days={r.days_until_due} />
                    }
                    <StatusBadge status={task.status} />
                  </div>

                  {/* Row 2: Indication + refill dates */}
                  <div className="flex items-center gap-2 text-xs text-gray-500 flex-wrap">
                    {p.indication && (
                      <span className="truncate max-w-[200px]" title={p.indication}>
                        🏥 {p.indication}
                      </span>
                    )}
                    {p.indication && (r.last_sale_date || r.due_date) && <span className="text-gray-300">·</span>}
                    {r.last_sale_date && <span>صُرف: <strong className="text-gray-600">{r.last_sale_date}</strong></span>}
                    {r.last_sale_date && r.due_date && <span className="text-gray-300">→</span>}
                    {r.due_date && (
                      <span>استحقاق: <strong className={isOverdue2 ? 'text-red-600' : 'text-gray-700'}>{r.due_date}</strong></span>
                    )}
                  </div>

                  {/* Row 3: ERP ref + dosing (secondary, compact) */}
                  {(r.docnumber || p.avg_daily_usage) && (
                    <div className="flex items-center gap-2 text-[11px] text-gray-400 flex-wrap">
                      {r.docnumber && (
                        <span
                          className="font-mono bg-gray-100 border border-gray-200 rounded px-1.5 py-0.5 text-gray-500 select-all"
                          title="رقم المستند في SOFTECH"
                          onClick={e => { e.stopPropagation(); navigator.clipboard?.writeText(r.docnumber) }}>
                          #{r.docnumber}
                        </span>
                      )}
                      {r.docnumber && p.avg_daily_usage && <span className="text-gray-300">·</span>}
                      {p.avg_daily_usage && (
                        <span className="text-amber-600">
                          {p.avg_daily_usage}/يوم · {p.expected_duration_days} يوم
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Per-task quick action */}
                <div className="flex-shrink-0" onClick={e => e.stopPropagation()}>
                  {isActive && (
                    <button
                      onClick={() => onQuickAction(task)}
                      className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-600 hover:border-brand-300 hover:text-brand-700 transition-colors">
                      تسجيل
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────
//  Assign Panel — multi-user, role, branch
// ─────────────────────────────────────────────
const ROLE_OPTIONS = [
  { value: '',              label: '— كل الأدوار —' },
  { value: 'call_center',   label: 'سنترال' },
  { value: 'pharmacist',    label: 'صيدلاني' },
  { value: 'salesperson',   label: 'مندوب مبيعات' },
  { value: 'admin',         label: 'مدير' },
  { value: 'supervisor',    label: 'مشرف' },
]

function AssignPanel({ task, acting, doAction, branches = [] }) {
  // Mode: 'specific' | 'role' | 'branch' | 'role_branch' | 'task_branch'
  const [mode,           setMode]           = useState('specific')
  const [selectedIds,    setSelectedIds]    = useState([])   // specific user PKs
  const [selectedRole,   setSelectedRole]   = useState('')
  const [selectedBranch, setSelectedBranch] = useState('')
  const [replace,        setReplace]        = useState(true)
  const [preview,        setPreview]        = useState([])   // resolved preview

  // Load staff based on current mode for preview
  const previewParams = (() => {
    const p = { is_active: true, page_size: 200 }
    if (mode === 'role'        && selectedRole)   p.role   = selectedRole
    if (mode === 'branch'      && selectedBranch) p.branch = selectedBranch
    if (mode === 'role_branch')                  {
      if (selectedRole)   p.role   = selectedRole
      if (selectedBranch) p.branch = selectedBranch
    }
    if (mode === 'task_branch' && task.branch)   p.branch = task.branch
    return p
  })()

  const { data: allStaff = [] } = useQuery({
    queryKey: ['staff-active'],
    queryFn:  () => import('../api/client').then(m =>
      m.default.get('/users/staff/', { params: { is_active: true, page_size: 200 } })
        .then(r => r.data.results || r.data)
    ).catch(() => []),
    staleTime: 5 * 60_000,
  })

  const { data: filteredStaff = [] } = useQuery({
    queryKey: ['staff-preview', previewParams],
    queryFn:  () => import('../api/client').then(m =>
      m.default.get('/users/staff/', { params: previewParams })
        .then(r => r.data.results || r.data)
    ).catch(() => []),
    enabled: mode !== 'specific',
    staleTime: 60_000,
  })

  const canSubmit = (() => {
    if (mode === 'specific')    return selectedIds.length > 0
    if (mode === 'role')        return !!selectedRole
    if (mode === 'branch')      return !!selectedBranch
    if (mode === 'role_branch') return !!(selectedRole || selectedBranch)
    if (mode === 'task_branch') return !!task.branch
    return false
  })()

  const buildPayload = () => {
    const p = { replace }
    if (mode === 'specific')    p.assignee_ids = selectedIds
    if (mode === 'role')        p.role = selectedRole
    if (mode === 'branch')      p.branch_id = parseInt(selectedBranch)
    if (mode === 'role_branch') {
      if (selectedRole)   p.role      = selectedRole
      if (selectedBranch) p.branch_id = parseInt(selectedBranch)
    }
    if (mode === 'task_branch') p.use_task_branch = true
    return p
  }

  const toggleUser = (id) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const currentAssignees = task.assignments_list || []

  return (
    <div className="mt-3 space-y-3">
      {/* Current assignees */}
      {currentAssignees.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-bold text-gray-500">المُسندون حالياً</div>
          <div className="flex flex-wrap gap-1.5">
            {currentAssignees.map(a => (
              <span key={a.staff_id}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-blue-50 border border-blue-100 text-blue-800">
                👤 {a.name}
                <span className="text-blue-400 text-[10px]">({a.role_label})</span>
              </span>
            ))}
          </div>
          <button
            disabled={acting}
            onClick={() => doAction(() => followupsApi.clearAssignments(task.id))}
            className="text-xs text-red-400 hover:text-red-600 underline disabled:opacity-50">
            إزالة كل الإسنادات
          </button>
        </div>
      )}

      {/* Mode selector */}
      <div>
        <div className="text-xs font-bold text-gray-500 mb-1.5">إسناد إلى</div>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {[
            { id: 'specific',    icon: '👤', label: 'موظف محدد' },
            { id: 'role',        icon: '🏷', label: 'دور وظيفي' },
            { id: 'branch',      icon: '🏪', label: 'فرع معين' },
            { id: 'role_branch', icon: '🎯', label: 'دور + فرع' },
            { id: 'task_branch', icon: '📍', label: 'فرع المهمة' },
          ].map(m => (
            <button key={m.id}
              onClick={() => setMode(m.id)}
              className={`flex items-center gap-1.5 px-2 py-2 rounded-xl text-xs font-semibold border transition-all ${
                mode === m.id
                  ? 'bg-brand-100 border-brand-400 text-brand-700 ring-1 ring-brand-400'
                  : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'
              }`}>
              {m.icon} {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* Mode-specific controls */}
      {mode === 'specific' && (
        <div className="space-y-1.5">
          <div className="text-xs text-gray-400">اختر موظفاً أو أكثر (يمكن التعدد)</div>
          <div className="max-h-44 overflow-y-auto border border-gray-100 rounded-xl divide-y divide-gray-50">
            {allStaff.map(s => (
              <label key={s.id}
                className={`flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-gray-50 ${
                  selectedIds.includes(s.id) ? 'bg-brand-50' : ''
                }`}>
                <input type="checkbox"
                  className="w-4 h-4 accent-brand-600 flex-shrink-0"
                  checked={selectedIds.includes(s.id)}
                  onChange={() => toggleUser(s.id)} />
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-gray-800 truncate">{s.full_name}</div>
                  <div className="text-xs text-gray-400">{s.role_label || s.role} · {s.branch_name || '—'}</div>
                </div>
              </label>
            ))}
          </div>
          {selectedIds.length > 0 && (
            <div className="text-xs text-brand-600 font-semibold">{selectedIds.length} موظف محدد</div>
          )}
        </div>
      )}

      {(mode === 'role' || mode === 'role_branch') && (
        <div>
          <label className="text-xs font-bold text-gray-500 block mb-1">الدور الوظيفي</label>
          <select className="input-field text-sm"
            value={selectedRole} onChange={e => setSelectedRole(e.target.value)}>
            {ROLE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      )}

      {(mode === 'branch' || mode === 'role_branch') && (
        <div>
          <label className="text-xs font-bold text-gray-500 block mb-1">الفرع</label>
          <select className="input-field text-sm"
            value={selectedBranch} onChange={e => setSelectedBranch(e.target.value)}>
            <option value="">— اختر فرعاً —</option>
            {branches.map(b => (
              <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
            ))}
          </select>
        </div>
      )}

      {mode === 'task_branch' && (
        <div className="text-xs p-2 bg-blue-50 border border-blue-100 rounded-xl text-blue-700">
          سيتم الإسناد لجميع موظفي الفرع المرتبط بالمهمة:
          <strong className="mr-1">{task.branch_name || `فرع ${task.sales_channel}`}</strong>
        </div>
      )}

      {/* Preview list for non-specific modes */}
      {mode !== 'specific' && filteredStaff.length > 0 && (
        <div className="text-xs space-y-1">
          <div className="text-gray-400 font-semibold">
            معاينة — {filteredStaff.length} موظف سيتم الإسناد إليهم:
          </div>
          <div className="flex flex-wrap gap-1">
            {filteredStaff.slice(0, 8).map(s => (
              <span key={s.id} className="px-2 py-0.5 bg-gray-100 rounded-full text-gray-600 text-[11px]">
                {s.full_name}
              </span>
            ))}
            {filteredStaff.length > 8 && (
              <span className="px-2 py-0.5 bg-gray-100 rounded-full text-gray-500 text-[11px]">
                +{filteredStaff.length - 8}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Replace toggle */}
      <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
        <input type="checkbox" className="w-3.5 h-3.5 accent-brand-600"
          checked={replace} onChange={e => setReplace(e.target.checked)} />
        <span className="text-gray-600">
          {replace ? 'استبدال الإسنادات الحالية' : 'إضافة فوق الإسنادات الحالية'}
        </span>
      </label>

      {/* Submit */}
      <button
        disabled={acting || !canSubmit}
        onClick={() => doAction(() => followupsApi.assign(task.id, buildPayload()))}
        className="w-full btn-primary text-sm py-2.5 disabled:opacity-50">
        {acting ? 'جارٍ الإسناد...' : '✅ تأكيد الإسناد'}
      </button>
    </div>
  )
}

// ─────────────────────────────────────────────
//  Task Detail Drawer
// ─────────────────────────────────────────────
function TaskDrawer({ taskId, onClose, onMutate, branches = [] }) {
  const assignPanelBranches = branches
  const qc = useQueryClient()
  const { data: task, isLoading } = useQuery({
    queryKey: ['followup-detail', taskId],
    queryFn:  () => followupsApi.detail(taskId).then(r => r.data),
    enabled:  !!taskId,
  })

  const [note, setNote]                       = useState('')
  const [callStatus, setCallStatus]           = useState('answered')
  const [callNotes, setCallNotes]             = useState('')
  const [tab, setTab]                         = useState('overview')
  const [acting, setActing]                   = useState(false)
  // Editable WhatsApp message — seeded from server when task loads
  const [waMsg, setWaMsg]                     = useState('')
  // Outcome 2-step state (mirrors QuickActionModal)
  const [outcomeBucket,     setOutcomeBucket]     = useState('')
  const [outcomePreset,     setOutcomePreset]     = useState('')
  const [outcomeSideResult, setOutcomeSideResult] = useState(null)

  // Seed editable message whenever the task detail loads
  useEffect(() => {
    if (task?.whatsapp_message) {
      setWaMsg(task.whatsapp_message)
    }
  }, [task?.whatsapp_message])

  const doAction = async (fn) => {
    setActing(true)
    try { await fn() } finally {
      setActing(false)
      qc.invalidateQueries(['followup-detail', taskId])
      onMutate()
    }
  }

  if (!taskId) return null
  const c   = task?.customer   || {}
  const p   = task?.product    || {}
  const r   = task?.refill     || {}
  const isOverdue = r.is_overdue || r.days_overdue > 0

  return (
    <div className="fixed inset-0 z-50 flex" dir="rtl">
      {/* Backdrop — only close when the backdrop itself is clicked, not the drawer content.
          Use onMouseDown+onMouseUp guard so scroll gestures (which can generate synthetic
          clicks on touch/trackpad) never accidentally close the drawer. */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onMouseDown={e => { e._backdropMouseDown = true }}
        onClick={e => { if (e._backdropMouseDown) onClose() }} />
      {/* Drawer content — stopPropagation so no click ever reaches the backdrop */}
      <div className="relative mr-auto w-full max-w-2xl bg-white h-full flex flex-col shadow-2xl overflow-hidden z-10"
        onClick={e => e.stopPropagation()}>

        {/* Drawer header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 flex-shrink-0">
          <div>
            <h2 className="font-black text-gray-900 text-base">
              {isLoading ? '...' : (c.name || 'تفاصيل المهمة')}
            </h2>
            {task && (
              <div className="flex items-center gap-2 mt-1">
                <StatusBadge status={task.status} />
                <ChannelBadge code={c.channel_code || task.sales_channel} />
                {isOverdue && <OverdueBadge days={r.days_overdue} />}
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl p-1">✕</button>
        </div>

        {/* Tab bar */}
        <div className="flex gap-0 border-b border-gray-100 flex-shrink-0 overflow-x-auto">
          {[
            { id: 'overview',   label: '📋 ملخص' },
            { id: 'product',    label: '💊 المنتج' },
            { id: 'whatsapp',   label: '💬 واتساب' },
            { id: 'cross_sell', label: `🛒 مكمّلات (${task?.complementary?.length || 0})` },
            { id: 'history',    label: `📞 السجل (${task?.call_history?.length || 0})` },
          ].map(t => (
            <button key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-2.5 text-xs font-semibold whitespace-nowrap transition-colors border-b-2 ${
                tab === t.id
                  ? 'border-brand-600 text-brand-700 bg-brand-50'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {isLoading ? (
            <div className="space-y-3 animate-pulse">
              {[1,2,3].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl" />)}
            </div>
          ) : !task ? (
            <div className="text-center py-12 text-gray-400">تعذّر تحميل البيانات</div>
          ) : (
            <>
              {/* ── OVERVIEW TAB ── */}
              {tab === 'overview' && (
                <div className="space-y-4">
                  {/* Customer card */}
                  <Section title="👤 بيانات العميل">
                    {c.source === 'local_customer' && (
                      <div className="mb-2 px-2 py-1.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-700">
                        ⚠ عميل PIC — لم يُربط بعد بملف عميل كامل في النظام
                      </div>
                    )}
                    {c.source === 'phcode_only' && (
                      <div className="mb-2 px-2 py-1.5 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-500">
                        كود ERP فقط — لا يوجد سجل عميل مرتبط
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <Field label="الاسم"      val={c.name} />
                      <Field label="القناة"     val={<ChannelBadge code={c.channel_code || task.sales_channel} size="md" />} />
                      <Field label="الموبايل"
                        val={
                          c.phone_available
                            ? <PhoneDisplay phone={c.phone} canSeePhone={c.can_see_phone !== false} />
                            : <span className="text-xs text-gray-300">غير مسجّل</span>
                        }
                      />
                      <Field label="واتساب"
                        val={
                          c.phone_available
                            ? <PhoneDisplay phone={c.whatsapp_phone || c.phone} canSeePhone={c.can_see_phone !== false} />
                            : <span className="text-xs text-gray-300">غير مسجّل</span>
                        }
                      />
                      <Field label="كود ERP"    val={c.phcode} mono />
                      <Field label="الشريحة"    val={c.segment ? <SegmentBadge segment={c.segment} /> : null} />
                      <Field label="آخر زيارة"  val={c.days_since_last_visit ? `${c.days_since_last_visit} يوم` : '—'} />
                      <Field label="LTV"         val={c.ltv > 0 ? `${c.ltv?.toLocaleString('en-US')} ج` : '—'} />
                    </div>
                    {c.churn_score > 0 && (
                      <div className="mt-2">
                        <div className="text-xs text-gray-500 mb-1">
                          خطر الانقطاع — {c.churn_segment}
                        </div>
                        <ChurnBar score={c.churn_score} segment={c.churn_segment} />
                      </div>
                    )}
                  </Section>

                  {/* Refill timing + full SOFTECH transaction reference */}
                  <Section title="📅 توقيت إعادة الصرف وبيانات الفاتورة">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <Field label="آخر صرف"           val={r.last_sale_date} />
                      <Field label="موعد الاستحقاق"    val={r.due_date} />
                      <Field label="حالة الاستحقاق"   val={<DaysUntilBadge days={r.days_until_due} />} />
                      <Field label="الفرع"              val={r.branch_name || (r.softech_branch_code ? `فرع ${r.softech_branch_code}` : null)} />
                    </div>

                    {/* SOFTECH ERP Transaction Block */}
                    {r.docnumber && (
                      <div className="mt-3 p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2">
                        <div className="text-xs font-bold text-slate-500 uppercase tracking-wide mb-2">
                          🔎 مرجع SOFTECH ERP
                        </div>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                          <div>
                            <div className="text-xs text-gray-400">رقم المستند</div>
                            <div className="font-mono font-bold text-gray-800 select-all text-base">
                              {r.docnumber}
                            </div>
                          </div>
                          <div>
                            <div className="text-xs text-gray-400">كود الفرع (ERP)</div>
                            <div className="font-mono font-semibold text-gray-700 select-all">
                              {r.softech_branch_code || '—'}
                            </div>
                          </div>
                          {r.total_amount != null && (
                            <div>
                              <div className="text-xs text-gray-400">إجمالي الفاتورة</div>
                              <div className="font-semibold text-gray-800">
                                {r.total_amount.toLocaleString('en-US', { minimumFractionDigits: 2 })} ج
                              </div>
                            </div>
                          )}
                          {r.item_qty != null && (
                            <div>
                              <div className="text-xs text-gray-400">الكمية المباعة</div>
                              <div className="font-semibold text-gray-800">{r.item_qty} وحدة</div>
                            </div>
                          )}
                          {r.item_price != null && (
                            <div>
                              <div className="text-xs text-gray-400">سعر الوحدة عند البيع</div>
                              <div className="font-semibold text-gray-800">
                                {r.item_price.toLocaleString('en-US', { minimumFractionDigits: 2 })} ج
                              </div>
                            </div>
                          )}
                          {r.item_line_total != null && (
                            <div>
                              <div className="text-xs text-gray-400">إجمالي السطر</div>
                              <div className="font-semibold text-emerald-700">
                                {r.item_line_total.toLocaleString('en-US', { minimumFractionDigits: 2 })} ج
                              </div>
                            </div>
                          )}
                        </div>
                        <button
                          onClick={() => navigator.clipboard?.writeText(r.docnumber)}
                          className="mt-1 text-xs text-slate-500 hover:text-brand-600 flex items-center gap-1">
                          📋 نسخ رقم المستند للبحث في SOFTECH
                        </button>
                      </div>
                    )}
                    {!r.docnumber && (
                      <div className="mt-2 text-xs text-gray-400 italic">
                        رقم المستند غير متوفر — شغّل "تحديث بيانات المعاملات" من لوحة الإدارة
                      </div>
                    )}
                  </Section>

                  {/* Quick product summary */}
                  <Section title="💊 الصنف">
                    <div className="text-sm font-bold text-brand-700 mb-1">{p.name}</div>
                    {p.indication && <div className="text-xs text-gray-500">🏥 {p.indication}</div>}
                    {p.dosage_form && <div className="text-xs text-gray-400 mt-0.5">{p.dosage_form} · {p.pack_size_label}</div>}
                  </Section>

                  {/* Action log */}
                  {task.notes && (
                    <Section title="📝 ملاحظات">
                      <p className="text-sm text-gray-700 whitespace-pre-wrap">{task.notes}</p>
                    </Section>
                  )}

                  {/* Pin + Assign section */}
                  <Section title="📌 تثبيت وإسناد">
                    <div className="flex items-center gap-3 flex-wrap">
                      <button
                        disabled={acting}
                        onClick={() => doAction(() =>
                          task.is_pinned
                            ? followupsApi.unpin(task.id)
                            : followupsApi.pin(task.id)
                        )}
                        className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold border transition-all disabled:opacity-50 ${
                          task.is_pinned
                            ? 'bg-amber-100 border-amber-400 text-amber-700 hover:bg-amber-200'
                            : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-amber-50 hover:border-amber-300'
                        }`}>
                        📌 {task.is_pinned ? 'إلغاء التثبيت' : 'تثبيت للمتابعة'}
                      </button>
                      {task.is_pinned && task.pinned_by_name && (
                        <span className="text-xs text-gray-400">ثبّتها: {task.pinned_by_name}</span>
                      )}
                    </div>
                    <AssignPanel task={task} acting={acting} doAction={doAction} branches={assignPanelBranches} />
                  </Section>

                  {/* Action buttons — outcome presets (2-step: bucket → preset) */}
                  {['pending', 'called'].includes(task.status) && (
                    <Section title="⚡ تسجيل النتيجة">
                      {outcomeSideResult?.action === 'demand_created' ? (
                        <div className="p-3 bg-purple-50 border border-purple-200 rounded-xl text-sm text-purple-800 space-y-2">
                          <div className="font-bold">✅ تم إنشاء طلب تلقائياً!</div>
                          <div>رقم الطلب: <strong className="font-mono">{outcomeSideResult.demand_number}</strong></div>
                          <button onClick={() => setOutcomeSideResult(null)}
                            className="text-xs text-purple-600 underline">
                            إغلاق
                          </button>
                        </div>
                      ) : (
                        <>
                          {/* Step 1: Outcome bucket */}
                          <div className="text-xs font-bold text-gray-400 mb-2">١. ما الذي حدث؟</div>
                          <div className="grid grid-cols-3 gap-2 mb-3">
                            {OUTCOME_BUCKETS.map(b => {
                              const ACTIVE_CLS = {
                                green: 'bg-green-500 text-white border-green-500',
                                blue:  'bg-blue-500  text-white border-blue-500',
                                red:   'bg-red-500   text-white border-red-500',
                              }
                              const active = outcomeBucket === b.id
                              return (
                                <button key={b.id}
                                  onClick={() => { setOutcomeBucket(b.id); setOutcomePreset('') }}
                                  className={`py-2.5 rounded-xl text-xs font-bold border-2 transition-all ${
                                    active
                                      ? ACTIVE_CLS[b.color] || 'bg-gray-800 text-white border-gray-700'
                                      : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
                                  }`}>
                                  {b.label}
                                </button>
                              )
                            })}
                          </div>

                          {/* Step 2: Specific preset */}
                          {outcomeBucket && (
                            <>
                              <div className="text-xs font-bold text-gray-400 mb-2">٢. التفاصيل</div>
                              <div className="grid grid-cols-2 gap-1.5 mb-3">
                                {LOCAL_PRESETS
                                  .filter(pr => OUTCOME_BUCKETS.find(b => b.id === outcomeBucket)?.presets.includes(pr.id))
                                  .map(pr => {
                                    const bucketColor = OUTCOME_BUCKETS.find(b => b.id === outcomeBucket)?.color || 'green'
                                    const SEL = {
                                      green: 'border-green-400 bg-green-50 text-green-800 ring-1 ring-green-400',
                                      blue:  'border-blue-400  bg-blue-50  text-blue-800  ring-1 ring-blue-400',
                                      red:   'border-red-400   bg-red-50   text-red-800   ring-1 ring-red-400',
                                    }
                                    return (
                                      <button key={pr.id}
                                        onClick={() => setOutcomePreset(pr.id)}
                                        className={`border-2 rounded-xl px-2 py-2.5 text-xs font-semibold text-right transition-all ${
                                          outcomePreset === pr.id
                                            ? SEL[bucketColor] || 'border-gray-400 bg-gray-50'
                                            : 'border-gray-100 bg-gray-50 text-gray-700 hover:bg-gray-100'
                                        }`}>
                                        {pr.label}
                                        {pr.side_action === 'create_demand' && (
                                          <span className="block text-[10px] text-purple-500 mt-0.5">+ طلب تلقائي</span>
                                        )}
                                        {pr.side_action === 'flag_phone' && (
                                          <span className="block text-[10px] text-orange-500 mt-0.5">+ تحديد رقم خاطئ</span>
                                        )}
                                      </button>
                                    )
                                  })}
                              </div>
                            </>
                          )}

                          {/* Optional note */}
                          <textarea rows={1} className="input-field resize-none text-sm mb-3"
                            placeholder="ملاحظة إضافية (اختيارية)..."
                            value={note} onChange={e => setNote(e.target.value)} />

                          {/* Submit button — only visible when preset is chosen */}
                          {outcomePreset && (
                            <button
                              disabled={acting}
                              onClick={async () => {
                                setActing(true)
                                try {
                                  const res = await followupsApi.applyOutcome(task.id, outcomePreset, note)
                                  if (res.data?.side_result?.action === 'demand_created') {
                                    setOutcomeSideResult(res.data.side_result)
                                  } else {
                                    setOutcomeBucket(''); setOutcomePreset('')
                                  }
                                  qc.invalidateQueries(['followup-detail', taskId])
                                  onMutate()
                                } finally { setActing(false) }
                              }}
                              className={`w-full py-2.5 rounded-xl text-sm font-bold text-white transition-all disabled:opacity-40 ${
                                { green: 'bg-green-600 hover:bg-green-700', blue: 'bg-blue-600 hover:bg-blue-700', red: 'bg-red-600 hover:bg-red-700' }[
                                  OUTCOME_BUCKETS.find(b => b.id === outcomeBucket)?.color
                                ] || 'bg-brand-600'
                              }`}>
                              {acting
                                ? 'جارٍ التسجيل...'
                                : `✅ تسجيل — ${LOCAL_PRESETS.find(p => p.id === outcomePreset)?.label}`}
                            </button>
                          )}
                        </>
                      )}
                    </Section>
                  )}

                  {/* Post-conversion actions — voucher & demand (for done tasks) */}
                  {task.status === 'done' && (
                    <Section title="🎁 إجراءات ما بعد التحويل">
                      <div className="space-y-2">
                        <div className="flex gap-2">
                          <input type="text" className="input-field text-sm flex-1"
                            placeholder="كود القسيمة..."
                            id={`voucher-input-${task.id}`} />
                          <button
                            disabled={acting}
                            onClick={async () => {
                              const code = document.getElementById(`voucher-input-${task.id}`)?.value?.trim()
                              if (!code) return
                              try {
                                await followupsApi.assignVoucher(task.id, code)
                                alert(`✅ القسيمة ${code} خُصِّصت للعميل`)
                              } catch (e) {
                                alert('فشل: ' + (e?.response?.data?.detail || e.message))
                              }
                            }}
                            className="btn-secondary text-xs px-3 whitespace-nowrap disabled:opacity-50">
                            🎟 منح قسيمة
                          </button>
                        </div>
                        {!task.demand_number && (
                          <button disabled={acting}
                            onClick={() => doAction(() => followupsApi.createDemand(task.id))}
                            className="w-full text-xs py-2 rounded-xl border border-purple-200 bg-purple-50 text-purple-700 hover:bg-purple-100 transition-all disabled:opacity-50">
                            📋 إنشاء طلب للصنف
                          </button>
                        )}
                      </div>
                    </Section>
                  )}

                  {/* Phone flag actions */}
                  <Section title="📞 إدارة الاتصال">
                    <div className="flex gap-2">
                      {!task.phone_invalid ? (
                        <button disabled={acting}
                          onClick={() => doAction(() => followupsApi.flagPhone(task.id))}
                          className="text-xs px-3 py-2 rounded-xl border border-gray-200 bg-gray-50 text-gray-600 hover:bg-red-50 hover:border-red-300 hover:text-red-700 transition-all disabled:opacity-50">
                          📵 تحديد الرقم كخاطئ
                        </button>
                      ) : (
                        <button disabled={acting}
                          onClick={() => doAction(() => followupsApi.unflagPhone(task.id))}
                          className="text-xs px-3 py-2 rounded-xl border border-green-200 bg-green-50 text-green-700 hover:bg-green-100 transition-all disabled:opacity-50">
                          ✅ الرقم صحيح الآن
                        </button>
                      )}
                    </div>
                  </Section>
                </div>
              )}

              {/* ── PRODUCT TAB ── */}
              {tab === 'product' && (
                <div className="space-y-4">
                  <Section title="💊 بيانات المنتج الكاملة">
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <Field label="الاسم التجاري"    val={p.name} />
                      <Field label="الاسم العلمي"     val={p.name_scientific} />
                      <Field label="المادة الفعّالة"  val={p.active_ingredients} />
                      <Field label="التشخيص / الاستخدام" val={p.indication} />
                      <Field label="الشكل الدوائي"    val={p.dosage_form} />
                      <Field label="حجم العبوة"        val={p.pack_size_label} />
                      <Field label="نوع الدواء"        val={p.medicine_type} />
                      <Field label="سعر العبوة"        val={p.pack_price ? `${p.pack_price} ج` : '—'} />
                    </div>
                  </Section>

                  {p.avg_daily_usage && (
                    <Section title="⏱ جدولة إعادة الصرف">
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <Field label="الاستخدام اليومي"  val={`${p.avg_daily_usage} وحدة/يوم`} />
                        <Field label="مدة العبوة المتوقعة" val={`${p.expected_duration_days} يوم`} />
                      </div>
                      <div className="mt-3 p-3 bg-amber-50 border border-amber-100 rounded-xl text-xs text-amber-800">
                        💡 بناءً على {p.avg_daily_usage} وحدة/يوم و{p.profile_pack_size || '—'} وحدة/عبوة،
                        الدواء يكفي <strong>{p.expected_duration_days} يوم</strong>.
                        ينبغي الاتصال بالعميل لإعادة الصرف قبل {task.chronic_profile?.followup_before_days || 5} أيام من النفاد.
                      </div>
                    </Section>
                  )}
                </div>
              )}

              {/* ── WHATSAPP TAB ── */}
              {tab === 'whatsapp' && (
                <div className="space-y-4">

                  {/* Phone status banner */}
                  {!c.phone_available ? (
                    <div className="flex items-center gap-2 p-3 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-500">
                      <span className="text-2xl">📵</span>
                      <div>
                        <div className="font-semibold">لا يوجد رقم مسجّل لهذا العميل</div>
                        <div className="text-xs mt-0.5">لا يمكن إرسال واتساب أو إجراء مكالمة</div>
                      </div>
                    </div>
                  ) : !c.can_see_phone ? (
                    <div className="flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700">
                      <span className="text-2xl">🔒</span>
                      <div>
                        <div className="font-semibold">رقم الهاتف محجوب</div>
                        <div className="text-xs mt-0.5">ليس لديك صلاحية رؤية بيانات الاتصال. تواصل مع المسؤول لمنح الصلاحية.</div>
                      </div>
                    </div>
                  ) : null}

                  {/* Editable WhatsApp message */}
                  {c.phone_available && c.can_see_phone && (
                    <Section title="💬 رسالة واتساب — قابلة للتعديل">
                      <div className="space-y-3">
                        {/* Chat bubble preview */}
                        <div className="bg-[#dcf8c6] border border-green-200 rounded-2xl rounded-tl-none p-3 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed" dir="rtl">
                          {waMsg || task.whatsapp_message || '...'}
                        </div>

                        {/* Editable textarea */}
                        <div>
                          <label className="text-xs font-bold text-gray-500 block mb-1">
                            ✏️ تعديل الرسالة قبل الإرسال
                          </label>
                          <textarea
                            rows={6}
                            className="input-field resize-y text-sm leading-relaxed"
                            dir="rtl"
                            value={waMsg || task.whatsapp_message || ''}
                            onChange={e => setWaMsg(e.target.value)}
                          />
                        </div>

                        {/* Action buttons */}
                        <div className="flex gap-2">
                          <a
                            href={`https://wa.me/${normalisePhone(c.whatsapp_phone || c.phone)}?text=${encodeURIComponent(waMsg || task.whatsapp_message || '')}`}
                            target="_blank" rel="noopener noreferrer"
                            onClick={() => doAction(() => followupsApi.whatsapp(task.id))}
                            className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl bg-green-500 hover:bg-green-600 text-white font-bold text-sm transition-colors">
                            💬 إرسال عبر واتساب
                          </a>
                          <button
                            onClick={() => navigator.clipboard?.writeText(waMsg || task.whatsapp_message || '')}
                            className="px-4 py-2.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-700 text-sm font-semibold transition-colors"
                            title="نسخ الرسالة">
                            📋
                          </button>
                          <button
                            onClick={() => setWaMsg(task.whatsapp_message || '')}
                            className="px-4 py-2.5 rounded-xl bg-gray-100 hover:bg-gray-200 text-gray-500 text-sm transition-colors"
                            title="إعادة تعيين الرسالة الافتراضية">
                            🔄
                          </button>
                        </div>

                        {/* Target number display */}
                        <div className="text-xs text-gray-400 flex items-center gap-2">
                          <span>الرقم المستهدف:</span>
                          <span dir="ltr" className="font-mono font-semibold text-gray-600">
                            {c.whatsapp_phone || c.phone}
                          </span>
                          {c.whatsapp_phone && c.whatsapp_phone !== c.phone && (
                            <span className="px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-[10px] font-bold">واتساب مخصص</span>
                          )}
                        </div>
                      </div>
                    </Section>
                  )}

                  {/* Log call section — shown regardless of phone visibility (call center can still log) */}
                  <Section title="📞 تسجيل مكالمة في سنترال">
                    <div className="space-y-3">
                      <div>
                        <label className="text-xs font-bold text-gray-500 block mb-1">حالة المكالمة</label>
                        <div className="flex gap-2 flex-wrap">
                          {[
                            { v: 'answered',  label: '✅ رد' },
                            { v: 'no_answer', label: '🔇 لا رد' },
                            { v: 'busy',      label: '📵 مشغول' },
                            { v: 'callback',  label: '🔄 معاد الاتصال' },
                          ].map(o => (
                            <button key={o.v}
                              onClick={() => setCallStatus(o.v)}
                              className={`px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                                callStatus === o.v
                                  ? 'bg-brand-100 border-brand-400 text-brand-700 ring-1 ring-brand-400'
                                  : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'
                              }`}>
                              {o.label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <label className="text-xs font-bold text-gray-500 block mb-1">ملاحظات المكالمة</label>
                        <textarea rows={2} className="input-field resize-none text-sm"
                          placeholder="ما الذي تم الاتفاق عليه؟"
                          value={callNotes} onChange={e => setCallNotes(e.target.value)} />
                      </div>
                      <div className="flex gap-2">
                        <button disabled={acting}
                          onClick={() => doAction(() => followupsApi.logCall(task.id, {
                            status: callStatus, notes: callNotes, mark_done: false,
                          }))}
                          className="flex-1 btn-secondary text-sm disabled:opacity-50">
                          {acting ? 'جارٍ...' : '📞 تسجيل مكالمة'}
                        </button>
                        <button disabled={acting}
                          onClick={() => doAction(() => followupsApi.logCall(task.id, {
                            status: callStatus, notes: callNotes, mark_done: true,
                          }))}
                          className="flex-1 btn-primary text-sm disabled:opacity-50">
                          {acting ? 'جارٍ...' : '✅ تسجيل + إغلاق'}
                        </button>
                      </div>
                    </div>
                  </Section>
                </div>
              )}

              {/* ── CROSS-SELL TAB ── */}
              {tab === 'cross_sell' && (
                <div className="space-y-3">
                  <div className="text-xs text-gray-400 bg-blue-50 border border-blue-100 rounded-xl px-3 py-2">
                    💡 منتجات يشتريها عملاء آخرون مع <strong>{p.name}</strong> — فرصة للبيع التكميلي
                  </div>
                  {(task.complementary || []).length === 0 ? (
                    <div className="text-center py-8 text-gray-400">
                      <div className="text-3xl mb-2">🔍</div>
                      <div>لا توجد توصيات مكمّلة بعد</div>
                    </div>
                  ) : (
                    (task.complementary || []).map((item, i) => (
                      <div key={item.id || i}
                        className="flex items-center gap-3 p-3 bg-white border border-gray-100 rounded-xl hover:border-brand-200 transition-colors">
                        <div className="w-8 h-8 rounded-lg bg-brand-50 flex items-center justify-center text-brand-600 font-bold text-xs flex-shrink-0">
                          {i + 1}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-sm text-gray-800 break-words">{item.name}</div>
                          {item.indication && (
                            <div className="text-xs text-gray-500 truncate">{item.indication}</div>
                          )}
                        </div>
                        {item.pack_price > 0 && (
                          <div className="text-sm font-bold text-emerald-600 flex-shrink-0">
                            {item.pack_price} ج
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* ── CALL HISTORY TAB ── */}
              {tab === 'history' && (
                <div className="space-y-3">
                  {(task.call_history || []).length === 0 ? (
                    <div className="text-center py-8 text-gray-400">
                      <div className="text-3xl mb-2">📭</div>
                      <div>لا يوجد سجل مكالمات سابق</div>
                    </div>
                  ) : (
                    (task.call_history || []).map(call => (
                      <div key={call.id}
                        className="p-3 bg-gray-50 border border-gray-100 rounded-xl text-sm">
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span>{call.direction === 'outbound' ? '📤' : '📥'}</span>
                            <span className="font-semibold text-gray-700">
                              {call.purpose === 'refill' ? 'متابعة صرف' : call.purpose}
                            </span>
                            <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                              call.status === 'answered' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                            }`}>
                              {call.status === 'answered' ? '✅ رد' : call.status}
                            </span>
                          </div>
                          <span className="text-xs text-gray-400">
                            {call.created_at ? format(parseISO(call.created_at), 'dd/MM HH:mm') : ''}
                          </span>
                        </div>
                        {call.summary && (
                          <div className="text-xs text-gray-600 mt-1">{call.summary}</div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────
//  Quick Action Modal (inline action without drawer)
// ─────────────────────────────────────────────
function QuickActionModal({ task, onClose, onDone }) {
  const [bucket,     setBucket]    = useState('')   // 'done' | 'called' | 'missed'
  const [preset,     setPreset]    = useState('')
  const [note,       setNote]      = useState('')
  const [saving,     setSaving]    = useState(false)
  const [sideResult, setSideResult] = useState(null)

  const c = task?.customer || {}
  const p = task?.product  || {}

  const bucketData    = OUTCOME_BUCKETS.find(b => b.id === bucket)
  const visiblePresets = bucket
    ? LOCAL_PRESETS.filter(pr => bucketData?.presets.includes(pr.id))
    : []
  const selectedPreset = LOCAL_PRESETS.find(pr => pr.id === preset)

  const BUCKET_COLORS = {
    green: { ring: 'ring-green-400', bg: 'bg-green-500', text: 'text-white', border: 'border-green-400',
             light: 'bg-green-50 border-green-200 text-green-800' },
    blue:  { ring: 'ring-blue-400',  bg: 'bg-blue-500',  text: 'text-white', border: 'border-blue-400',
             light: 'bg-blue-50 border-blue-200 text-blue-800'   },
    red:   { ring: 'ring-red-400',   bg: 'bg-red-500',   text: 'text-white', border: 'border-red-400',
             light: 'bg-red-50 border-red-200 text-red-800'      },
  }

  const submit = async () => {
    if (!preset) return
    setSaving(true)
    try {
      const res = await followupsApi.applyOutcome(task.id, preset, note)
      if (res.data?.side_result?.action === 'demand_created') {
        setSideResult(res.data.side_result)
        return
      }
      onDone()
    } catch { } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onMouseDown={e => { e._backdropMouseDown = true }}
        onClick={e => { if (e._backdropMouseDown) onClose() }} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 pt-4 pb-3 border-b border-gray-100 flex items-start justify-between">
          <div>
            <h3 className="font-black text-gray-900 text-base">تسجيل نتيجة المتابعة</h3>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <span className="font-semibold text-sm text-gray-700">{c.name || '—'}</span>
              <ChannelBadge code={c.channel_code || task.sales_channel} />
              {c.segment && <SegmentBadge segment={c.segment} />}
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl mt-0.5">✕</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Product summary */}
          <div className="flex items-center gap-3 p-3 bg-brand-50 border border-brand-100 rounded-xl">
            <div className="text-2xl flex-shrink-0">💊</div>
            <div className="min-w-0">
              <div className="font-bold text-brand-800 text-sm">{p.name || '—'}</div>
              {p.indication && <div className="text-xs text-gray-500 truncate">🏥 {p.indication}</div>}
              {p.dosage_form && <div className="text-xs text-gray-400">{p.dosage_form} · {p.pack_size_label}</div>}
              {c.phone_available && (
                <PhoneDisplay phone={c.phone} canSeePhone={c.can_see_phone !== false} className="mt-0.5" />
              )}
            </div>
          </div>

          {/* Side result — demand created */}
          {sideResult?.action === 'demand_created' && (
            <div className="p-4 bg-purple-50 border border-purple-200 rounded-xl text-sm text-purple-800 space-y-2">
              <div className="font-bold text-base">✅ تم إنشاء طلب تلقائياً!</div>
              <div>رقم الطلب: <strong className="font-mono">{sideResult.demand_number}</strong></div>
              <button onClick={onDone} className="w-full btn-primary text-sm">إغلاق</button>
            </div>
          )}

          {!sideResult && (
            <>
              {/* Step 1 — Status bucket */}
              <div>
                <div className="text-xs font-bold text-gray-400 mb-2">١. ما الذي حدث؟</div>
                <div className="grid grid-cols-3 gap-2">
                  {OUTCOME_BUCKETS.map(b => {
                    const colors = BUCKET_COLORS[b.color]
                    const active = bucket === b.id
                    return (
                      <button key={b.id}
                        onClick={() => { setBucket(b.id); setPreset('') }}
                        className={`py-3 rounded-xl text-sm font-bold border-2 transition-all ${
                          active
                            ? `${colors.bg} ${colors.text} ${colors.border}`
                            : `bg-white border-gray-200 text-gray-600 hover:border-gray-300`
                        }`}>
                        {b.label}
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Step 2 — Specific preset */}
              {bucket && (
                <div>
                  <div className="text-xs font-bold text-gray-400 mb-2">٢. التفاصيل</div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {visiblePresets.map(pr => {
                      const colors = BUCKET_COLORS[OUTCOME_BUCKETS.find(b => b.id === bucket)?.color]
                      return (
                        <button key={pr.id}
                          onClick={() => setPreset(pr.id)}
                          className={`border-2 rounded-xl px-3 py-2.5 text-xs font-semibold text-right transition-all ${
                            preset === pr.id
                              ? `${colors.border} ${colors.light} ring-1 ${colors.ring}`
                              : 'border-gray-100 bg-gray-50 text-gray-700 hover:bg-gray-100'
                          }`}>
                          {pr.label}
                          {pr.side_action === 'create_demand' && (
                            <span className="block text-[10px] text-purple-500 mt-0.5 font-normal">+ يُنشئ طلباً تلقائياً</span>
                          )}
                          {pr.side_action === 'flag_phone' && (
                            <span className="block text-[10px] text-orange-500 mt-0.5 font-normal">+ يُحدد الرقم كخاطئ</span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Note */}
              <textarea rows={2} className="input-field resize-none text-sm"
                placeholder="ملاحظة إضافية (اختيارية)..."
                value={note} onChange={e => setNote(e.target.value)} />

              {/* Submit */}
              <div className="flex gap-2">
                <button onClick={submit} disabled={saving || !preset}
                  className={`flex-1 py-2.5 rounded-xl text-sm font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
                    preset
                      ? `${BUCKET_COLORS[bucketData?.color]?.bg || 'bg-brand-600'} text-white`
                      : 'bg-gray-100 text-gray-400'
                  }`}>
                  {saving ? 'جارٍ التسجيل...' : preset ? `تسجيل — ${selectedPreset?.label}` : 'اختر التفاصيل أولاً'}
                </button>
                <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────
//  Small helpers
// ─────────────────────────────────────────────
function Section({ title, children }) {
  return (
    <div className="bg-gray-50 rounded-xl p-4">
      <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">{title}</div>
      {children}
    </div>
  )
}

function Field({ label, val, mono = false, dir: d }) {
  if (!val && val !== 0) return (
    <div>
      <div className="text-xs text-gray-400">{label}</div>
      <div className="text-sm text-gray-300">—</div>
    </div>
  )
  const isEl = typeof val === 'object' && val !== null && val.$$typeof
  return (
    <div>
      <div className="text-xs text-gray-400">{label}</div>
      {isEl ? val : (
        <div className={`text-sm font-semibold text-gray-800 ${mono ? 'font-mono' : ''}`} dir={d}>{val}</div>
      )}
    </div>
  )
}

function ActionBtn({ color, label, onClick, disabled }) {
  const cls = {
    blue:  'bg-blue-50  text-blue-700  border-blue-200  hover:bg-blue-100',
    green: 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100',
    red:   'bg-red-50   text-red-700   border-red-200   hover:bg-red-100',
  }[color] || ''
  return (
    <button onClick={onClick} disabled={disabled}
      className={`border rounded-xl py-2.5 text-sm font-bold transition-all disabled:opacity-50 ${cls}`}>
      {label}
    </button>
  )
}

function normalisePhone(phone) {
  if (!phone) return ''
  let clean = phone.replace(/\s|-|\+/g, '')
  if (clean.startsWith('0')) clean = '20' + clean.slice(1)
  return clean
}

// ─────────────────────────────────────────────
//  Main page
// ─────────────────────────────────────────────
const DEFAULT_FILTERS = {
  status:          'pending',
  task_type:       '',
  sales_channel:   [],
  favoured_only:   false,
  indication:      '',
  medicine_type:   '',
  segment:         '',
  churn_segment:   '',
  item_search:     '',
  customer_search: '',
  due_after:       '',
  due_before:      '',
  overdue_only:    false,
  branch:          '',
  by_priority:     false,
  ordering:        '',
  my_tasks:        false,
  pinned_only:     false,
  untracked:       false,
}

const PERSONAL_TABS = [
  { id: 'all',       label: 'كل المهام',        filters: { my_tasks: false, pinned_only: false, untracked: false } },
  { id: 'mine',      label: '👤 معينة لي',      filters: { my_tasks: true,  pinned_only: false, untracked: false } },
  { id: 'pinned',    label: '📌 المثبتة',       filters: { my_tasks: false, pinned_only: true,  untracked: false } },
  { id: 'untracked', label: '🔔 غير متابعة',   filters: { my_tasks: false, pinned_only: false, untracked: true  } },
  { id: 'priority',  label: '⚡ الأعلى أولوية', filters: { my_tasks: false, pinned_only: false, untracked: false, ordering: '-priority_score' } },
]

export default function FollowUpsPage() {
  const { user }  = useAuthStore()
  const qc        = useQueryClient()
  const [filters, setFilters]           = useState(DEFAULT_FILTERS)
  const [selectedTask, setSelectedTask] = useState(null)   // opens drawer
  const [quickTask,    setQuickTask]    = useState(null)   // opens quick modal
  const [regenerating, setRegenerating] = useState(false)
  const [selectedIds,  setSelectedIds]  = useState([])     // batch selection
  const [batchNote,       setBatchNote]       = useState('')
  const [batchRunning,    setBatchRunning]    = useState(false)
  const [showBatchPreset, setShowBatchPreset] = useState(false)
  const [batchPresetId,   setBatchPresetId]   = useState('')
  const [viewMode,        setViewMode]        = useState('grouped')  // 'list' | 'grouped'

  const toggleSelect = (id) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  const toggleAll = () =>
    setSelectedIds(prev => prev.length === tasks.length ? [] : tasks.map(t => t.id))
  const clearSelection = () => { setSelectedIds([]); setBatchNote(''); setShowBatchPreset(false) }

  // Build API params from filter state
  const apiParams = {
    ...(filters.status         && { status:          filters.status }),
    ...(filters.task_type      && { task_type:        filters.task_type }),
    ...(filters.sales_channel?.length && { sales_channel: filters.sales_channel.join(',') }),
    ...(filters.favoured_only  && { favoured_only:    '1' }),
    ...(filters.indication     && { indication:       filters.indication }),
    ...(filters.medicine_type  && { medicine_type:    filters.medicine_type }),
    ...(filters.segment        && { segment:          filters.segment }),
    ...(filters.churn_segment  && { churn_segment:    filters.churn_segment }),
    ...(filters.item_search    && { item_search:      filters.item_search }),
    ...(filters.customer_search && { customer_search: filters.customer_search }),
    ...(filters.due_after      && { due_after:        filters.due_after }),
    ...(filters.due_before     && { due_before:       filters.due_before }),
    ...(filters.overdue_only   && { overdue_only:     '1' }),
    ...(filters.branch         && { branch:           filters.branch }),
    ...(filters.by_priority    && { by_priority:      '1' }),
    ...(filters.ordering       && { ordering:         filters.ordering }),
    ...(filters.my_tasks       && { my_tasks:         '1' }),
    ...(filters.pinned_only    && { pinned_only:      '1' }),
    ...(filters.untracked      && { untracked:        '1' }),
    ...(filters.ordering       && { ordering:         filters.ordering }),
    hide_invalid: '1',   // hide invalid-phone tasks from main list by default
    page_size: 100,
  }

  const [personalTab, setPersonalTab] = useState('all')
  const applyPersonalTab = (tab) => {
    setPersonalTab(tab.id)
    setFilters(p => ({ ...p, ...tab.filters }))
  }

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const { data: stats } = useQuery({
    queryKey: ['followup-dashboard'],
    queryFn:  () => followupsApi.dashboard().then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: meta } = useQuery({
    queryKey: ['followup-filter-meta'],
    queryFn:  () => followupsApi.filterMeta().then(r => r.data),
    staleTime: 5 * 60_000,
  })

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['followup-tasks', apiParams],
    queryFn:  () => followupsApi.list(apiParams).then(r => r.data.results || r.data),
    refetchInterval: 60_000,
    enabled: viewMode === 'list',
  })

  const { data: groupedTasks = [], isLoading: isGroupedLoading } = useQuery({
    queryKey: ['followup-grouped', apiParams],
    queryFn:  () => followupsApi.grouped(apiParams).then(r => r.data),
    refetchInterval: 60_000,
    enabled: viewMode === 'grouped',
  })

  const invalidate = useCallback(() => {
    qc.invalidateQueries(['followup-tasks'])
    qc.invalidateQueries(['followup-grouped'])
    qc.invalidateQueries(['followup-dashboard'])
    setQuickTask(null)
  }, [qc])

  const onDrawerMutate = useCallback(() => {
    qc.invalidateQueries(['followup-tasks'])
    qc.invalidateQueries(['followup-grouped'])
    qc.invalidateQueries(['followup-dashboard'])
    if (selectedTask) qc.invalidateQueries(['followup-detail', selectedTask.id])
  }, [qc, selectedTask])

  const TAB_STATUSES = [
    { v: '',            label: 'الكل' },
    { v: 'pending',     label: `معلق (${stats?.pending || 0})`,     warn: false },
    { v: 'called',      label: `اتصلت (${stats?.called || 0})`,      warn: false },
    { v: 'done',        label: `مكتمل (${stats?.done || 0})`,        warn: false },
    { v: 'missed',      label: `فائت (${stats?.missed || 0})`,       warn: (stats?.missed || 0) > 0 },
    { v: 'auto_closed', label: `آلي (${stats?.auto_closed || 0})`,   warn: false },
  ]

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* ── Sticky header ── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20 shadow-sm">
        <div className="max-w-7xl mx-auto space-y-3">

          {/* Title row */}
          <div className="flex items-center gap-4 flex-wrap">
            <div>
              <h1 className="text-xl font-black text-gray-900">متابعة المبيعات والأدوية المزمنة</h1>
              <p className="text-xs text-gray-400 mt-0.5">
                إعادة الصرف · البيع التكميلي · التواصل عبر واتساب والسنترال
              </p>
            </div>
            <div className="flex-1" />
            <div className="flex items-center gap-2">
              <CanDo module="followups" action="view">
                <ModuleNotificationBell category="followups" label="إشعارات المتابعات" />
              </CanDo>
              {user?.role === 'admin' && (
                <>
                  <button
                    onClick={async () => {
                      try { await followupsApi.backfillChannels() } catch {}
                      qc.invalidateQueries(['followup-tasks'])
                    }}
                    className="btn-secondary text-xs px-3 py-2">
                    🔧 تحديث القنوات
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        const { data } = await followupsApi.backfillTxDetail()
                        alert(`تم تحديث ${data.tasks_updated} مهمة بتفاصيل المعاملة`)
                      } catch (e) {
                        alert('فشل: ' + (e?.response?.data?.detail || e.message))
                      }
                      qc.invalidateQueries(['followup-tasks'])
                    }}
                    className="btn-secondary text-xs px-3 py-2">
                    🧾 تحديث بيانات الفواتير
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        const { data } = await followupsApi.updatePriorityScores()
                        alert(`تم تحديث درجة الأولوية لـ ${data.tasks_updated} مهمة`)
                      } catch (e) { alert('فشل: ' + e.message) }
                      qc.invalidateQueries(['followup-tasks'])
                    }}
                    className="btn-secondary text-xs px-3 py-2">
                    ⚡ تحديث الأولويات
                  </button>
                  <button
                    onClick={async () => {
                      if (!confirm('سيتم إلغاء المهام المنتهية الصلاحية (5+ محاولات، 30+ يوم). متابعة؟')) return
                      try {
                        const { data } = await followupsApi.cleanupDead({ dry_run: false })
                        alert(`تم إلغاء ${data.cancelled} مهمة منتهية`)
                      } catch (e) { alert('فشل: ' + e.message) }
                      qc.invalidateQueries(['followup-tasks'])
                    }}
                    className="btn-secondary text-xs px-3 py-2 text-red-600">
                    🗑 تنظيف المهام الميتة
                  </button>
                  <button
                    onClick={async () => {
                      try {
                        const { data } = await followupsApi.deduplicate({ dry_run: true })
                        if (data.tasks_cancelled === 0) {
                          alert('✅ لا توجد مهام مكررة')
                          return
                        }
                        if (!confirm(`سيتم إلغاء ${data.tasks_cancelled} مهمة مكررة في ${data.groups_affected} مجموعة. متابعة؟`)) return
                        const { data: res } = await followupsApi.deduplicate({ dry_run: false })
                        alert(`✅ تم دمج ${res.tasks_cancelled} مهمة مكررة`)
                        qc.invalidateQueries(['followup-tasks'])
                        qc.invalidateQueries(['followup-grouped'])
                      } catch (e) { alert('فشل: ' + e.message) }
                    }}
                    className="btn-secondary text-xs px-3 py-2 text-orange-600">
                    🔀 إزالة التكرار
                  </button>
                  <RefreshButton
                    loading={regenerating}
                    size="sm"
                    onClick={async () => {
                      setRegenerating(true)
                      try {
                        const { data: result } = await followupsApi.generate({
                          dry_run: false, overdue_days: 3,
                        })
                        qc.invalidateQueries(['followup-tasks'])
                        qc.invalidateQueries(['followup-dashboard'])
                        const parts = []
                        if (result.tasks_created)    parts.push(`${result.tasks_created} مهمة جديدة`)
                        if (result.tasks_escalated)  parts.push(`${result.tasks_escalated} → فائت`)
                        if (result.tasks_auto_closed) parts.push(`${result.tasks_auto_closed} مُغلق آلياً`)
                        if (parts.length) alert('تم: ' + parts.join(' · '))
                      } catch (e) {
                        alert('فشل التحديث: ' + (e?.response?.data?.detail || e.message || ''))
                      } finally { setRegenerating(false) }
                    }}>
                    🔄 توليد المهام
                  </RefreshButton>
                </>
              )}
            </div>
          </div>

          {/* KPI strip */}
          {stats && (
            <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: 'none' }}>
              {[
                { label: 'معلق',         val: stats.pending,     color: '#f59e0b', bg: '#fffbeb' },
                { label: 'اتصلت',        val: stats.called,      color: '#3b82f6', bg: '#eff6ff' },
                { label: 'مستحق اليوم', val: stats.due_today,   color: '#ef4444', bg: '#fef2f2' },
                { label: 'متأخر',        val: stats.overdue,     color: '#dc2626', bg: '#fef2f2' },
                { label: 'فائت',         val: stats.missed,      color: '#991b1b', bg: '#fef2f2' },
                { label: 'مكتمل',        val: stats.done,        color: '#10b981', bg: '#f0fdf4' },
                { label: 'أُغلق آلياً', val: stats.auto_closed, color: '#8b5cf6', bg: '#f5f3ff' },
                { label: 'بروفايلات',   val: stats.chronic_profiles, color: '#6b7280', bg: '#f9fafb' },
              ].map(k => (
                <div key={k.label} className="flex-shrink-0 rounded-xl px-4 py-2 text-center min-w-[72px]"
                  style={{ background: k.bg, border: `1px solid ${k.color}30` }}>
                  <div className="text-[10px] text-gray-500 whitespace-nowrap">{k.label}</div>
                  <div className="text-xl font-black" style={{ color: k.color }}>{k.val ?? 0}</div>
                </div>
              ))}
            </div>
          )}

          {/* Channel priority legend — driven by live filter-meta */}
          <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
            <span className="font-semibold">القنوات:</span>
            {(meta?.channels || []).map(ch => {
              const cfg = getChannelCfg(ch.code)
              return (
                <span key={ch.code} className="flex items-center gap-1" style={{ color: cfg.color }}>
                  {cfg.icon} {ch.label}
                  {!ch.favoured && <span className="text-gray-400">(أقل)</span>}
                </span>
              )
            })}
          </div>

          {/* Overdue warning */}
          {(stats?.missed || 0) > 5 && (
            <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-center gap-2">
              ⚠️ <strong>{stats.missed} مهمة فائتة</strong> — هؤلاء العملاء في خطر انقطاع مرتفع وسيُستهدفون في حملات الاسترداد تلقائياً.
            </div>
          )}

          {/* View mode toggle + personal tabs row */}
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex bg-gray-100 rounded-xl p-0.5 gap-0.5 flex-shrink-0">
              {[
                { id: 'list',    icon: '☰', label: 'قائمة' },
                { id: 'grouped', icon: '👥', label: 'مجمّع بالعميل' },
              ].map(v => (
                <button key={v.id}
                  onClick={() => { setViewMode(v.id); clearSelection() }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    viewMode === v.id
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  }`}>
                  {v.icon} {v.label}
                </button>
              ))}
            </div>
          </div>

          {/* Personal view tabs */}
          <div className="flex gap-1 overflow-x-auto pb-0.5" style={{ scrollbarWidth: 'none' }}>
            {PERSONAL_TABS.map(t => (
              <button key={t.id}
                onClick={() => applyPersonalTab(t)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors border ${
                  personalTab === t.id
                    ? 'bg-gray-800 text-white border-gray-800'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'
                }`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Status tab strip */}
          <div className="flex gap-1 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
            {TAB_STATUSES.map(t => (
              <button key={t.v}
                onClick={() => setFilters(p => ({ ...p, status: t.v }))}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
                  filters.status === t.v
                    ? 'bg-brand-600 text-white'
                    : t.warn
                      ? 'bg-red-100 text-red-700 hover:bg-red-200'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}>
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Body ── */}
      <div className="max-w-7xl mx-auto px-6 py-5 space-y-4">

        {/* Advanced filter panel */}
        <FilterPanel
          filters={filters}
          setFilters={setFilters}
          meta={meta}
          branches={branches}
        />

        {/* Results count + select all (list view only) */}
        {viewMode === 'list' && !isLoading && (
          <div className="flex items-center gap-3 px-1">
            <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
              <input type="checkbox" className="w-3.5 h-3.5 accent-brand-600"
                checked={selectedIds.length === tasks.length && tasks.length > 0}
                onChange={toggleAll} />
              تحديد الكل
            </label>
            <span className="text-xs text-gray-400">
              {tasks.length} نتيجة
              {selectedIds.length > 0 && ` · ${selectedIds.length} محدد`}
              {filters.favoured_only && ' · المفضّلة'}
              {filters.overdue_only  && ' · المتأخرة'}
            </span>
          </div>
        )}

        {/* Results count (grouped view) */}
        {viewMode === 'grouped' && !isGroupedLoading && (
          <div className="text-xs text-gray-400 px-1">
            {groupedTasks.length} عميل
          </div>
        )}

        {/* Batch selection info — inline above list */}
        {viewMode === 'list' && selectedIds.length > 0 && (
          <div className="text-xs text-brand-700 font-semibold px-1 animate-pulse">
            {selectedIds.length} مهمة محددة — شاهد شريط الإجراءات أسفل الشاشة
          </div>
        )}

        {/* ── LIST VIEW ── */}
        {viewMode === 'list' && (isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[1,2,3,4,5].map(i => (
              <div key={i} className="h-24 bg-white border border-gray-100 rounded-xl" />
            ))}
          </div>
        ) : tasks.length === 0 ? (
          <div className="bg-white border border-gray-100 rounded-xl text-center py-14">
            <div className="text-4xl mb-3">💊</div>
            <div className="font-bold text-gray-600">لا توجد مهام متابعة</div>
            <div className="text-xs text-gray-400 mt-1">جرّب تغيير الفلاتر أو توليد مهام جديدة</div>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map(task => (
              <TaskCard
                key={task.id}
                task={task}
                onSelect={setSelectedTask}
                onQuickAction={setQuickTask}
                onPinToggle={invalidate}
                isSelected={selectedIds.includes(task.id)}
                onSelect2={toggleSelect}
              />
            ))}
          </div>
        ))}

        {/* ── GROUPED VIEW ── */}
        {viewMode === 'grouped' && (isGroupedLoading ? (
          <div className="space-y-3 animate-pulse">
            {[1,2,3].map(i => (
              <div key={i} className="h-40 bg-white border border-gray-100 rounded-2xl" />
            ))}
          </div>
        ) : groupedTasks.length === 0 ? (
          <div className="bg-white border border-gray-100 rounded-xl text-center py-14">
            <div className="text-4xl mb-3">👥</div>
            <div className="font-bold text-gray-600">لا توجد مهام</div>
          </div>
        ) : (
          <div className="space-y-3">
            {groupedTasks.map((group, idx) => (
              <CustomerGroupCard
                key={group.phcode || group.customer?.id || `group-${idx}`}
                group={group}
                onOpenTask={setSelectedTask}
                onQuickAction={setQuickTask}
                onMutate={invalidate}
              />
            ))}
          </div>
        ))}
      </div>

      {/* Drawer — keyed by task id so state resets cleanly per task */}
      {selectedTask && (
        <TaskDrawer
          key={selectedTask.id}
          taskId={selectedTask.id}
          onClose={() => setSelectedTask(null)}
          onMutate={onDrawerMutate}
          branches={branches}
        />
      )}

      {/* ── Feature 10: Floating batch action bar ── */}
      {viewMode === 'list' && selectedIds.length > 0 && (
        <div className="fixed bottom-0 inset-x-0 z-40 pointer-events-none" dir="rtl">
          <div className="max-w-7xl mx-auto px-4 pb-4 pointer-events-auto">
            <div className="bg-gray-900 rounded-2xl shadow-2xl overflow-hidden">

              {/* Inline preset picker — shown when apply_preset is active */}
              {showBatchPreset && (
                <div className="px-4 py-3 border-b border-gray-700 bg-gray-800">
                  <div className="text-xs font-bold text-gray-300 mb-2">اختر نتيجة لتطبيقها على {selectedIds.length} مهمة:</div>
                  <div className="flex flex-wrap gap-1.5">
                    {LOCAL_PRESETS.map(pr => (
                      <button key={pr.id}
                        disabled={batchRunning}
                        onClick={async () => {
                          setBatchRunning(true)
                          try {
                            const res = await followupsApi.bulkAction(
                              selectedIds, 'apply_preset', { preset_id: pr.id, note: batchNote },
                            )
                            const errs = res.data.errors?.length || 0
                            if (errs > 0) alert(`تم ${res.data.processed} · فشل ${errs}`)
                            invalidate(); clearSelection()
                          } catch { } finally { setBatchRunning(false) }
                        }}
                        className={`px-2.5 py-1.5 rounded-lg text-xs font-semibold border transition-all disabled:opacity-40 ${
                          batchPresetId === pr.id
                            ? 'bg-brand-600 text-white border-brand-600'
                            : 'bg-gray-700 border-gray-600 text-gray-200 hover:bg-gray-600'
                        }`}>
                        {pr.label}
                      </button>
                    ))}
                    <button onClick={() => setShowBatchPreset(false)}
                      className="px-2.5 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500">
                      ✕ إلغاء
                    </button>
                  </div>
                </div>
              )}

              <div className="p-3 flex items-center gap-2 flex-wrap">
                {/* Count + clear */}
                <div className="flex items-center gap-2">
                  <span className="text-white font-bold text-sm whitespace-nowrap">
                    {selectedIds.length} محدد
                  </span>
                  <button onClick={clearSelection}
                    className="text-gray-400 hover:text-white text-xs px-2 py-1 rounded-lg hover:bg-gray-700 transition-colors">
                    ✕ إلغاء
                  </button>
                </div>

                <div className="w-px h-6 bg-gray-700 flex-shrink-0" />

                {/* Status actions */}
                <div className="flex gap-1.5 flex-wrap">
                  {[
                    { action: 'mark_called', label: '📞 اتصلت',  bg: 'bg-blue-600  hover:bg-blue-500'  },
                    { action: 'mark_done',   label: '✅ اشتروا', bg: 'bg-green-600 hover:bg-green-500' },
                    { action: 'mark_missed', label: '❌ لا رد',   bg: 'bg-red-700   hover:bg-red-600'   },
                    { action: 'pin',         label: '📌 تثبيت',   bg: 'bg-amber-600 hover:bg-amber-500' },
                    { action: 'unpin',       label: '📌 إلغاء',   bg: 'bg-gray-600  hover:bg-gray-500'  },
                    { action: 'cancel',      label: '🗑 إلغاء مهمة', bg: 'bg-rose-800 hover:bg-rose-700' },
                  ].map(b => (
                    <button key={b.action} disabled={batchRunning}
                      onClick={async () => {
                        if (b.action === 'cancel' && !confirm(`إلغاء ${selectedIds.length} مهمة؟`)) return
                        setBatchRunning(true)
                        try {
                          const res = await followupsApi.bulkAction(
                            selectedIds, b.action, { note: batchNote },
                          )
                          const errs = res.data.errors?.length || 0
                          if (errs > 0) alert(`تم ${res.data.processed} · فشل ${errs}`)
                          invalidate(); clearSelection()
                        } catch { } finally { setBatchRunning(false) }
                      }}
                      className={`px-3 py-2 rounded-xl text-xs font-bold text-white transition-all disabled:opacity-40 ${b.bg}`}>
                      {b.label}
                    </button>
                  ))}

                  {/* Apply preset — opens inline picker */}
                  <button disabled={batchRunning}
                    onClick={() => setShowBatchPreset(p => !p)}
                    className={`px-3 py-2 rounded-xl text-xs font-bold text-white transition-all disabled:opacity-40 ${
                      showBatchPreset
                        ? 'bg-brand-700 ring-1 ring-brand-400'
                        : 'bg-brand-600 hover:bg-brand-500'
                    }`}>
                    ⚡ تطبيق نتيجة
                  </button>
                </div>

                <div className="w-px h-6 bg-gray-700 flex-shrink-0" />

                {/* Campaign button */}
                <button disabled={batchRunning}
                  onClick={async () => {
                    const campName = prompt('اسم الحملة:')
                    if (!campName) return
                    const template = `أهلا بحضرتك يا فندم،\n{{customer_name}} 🌿\n\nنتواصل معكم من صيدلية الرزيقي للتذكير بدواء/منتج (*{{item_name}}*) يقترب موعد نفاده.\n\nصيدليات الرزيقي — نهتم بصحتكم 💙`
                    setBatchRunning(true)
                    try {
                      const res = await followupsApi.createCampaign({
                        task_ids: selectedIds, name: campName, message_template: template,
                      })
                      alert(`✅ حملة "${campName}" أُنشئت — ${res.data.estimated_reach} رسالة`)
                      clearSelection()
                    } catch (e) {
                      alert('فشل: ' + (e?.response?.data?.detail || e.message))
                    } finally { setBatchRunning(false) }
                  }}
                  className="px-3 py-2 rounded-xl text-xs font-bold text-white bg-purple-600 hover:bg-purple-500 transition-all disabled:opacity-40">
                  📣 حملة واتساب
                </button>

                {/* Note field */}
                <input type="text" dir="rtl"
                  className="flex-1 min-w-32 bg-gray-800 border border-gray-700 text-white text-xs rounded-xl px-3 py-2 placeholder-gray-500 focus:outline-none focus:border-gray-500"
                  placeholder="ملاحظة للإجراء..."
                  value={batchNote} onChange={e => setBatchNote(e.target.value)} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Quick action modal — keyed by task id so state resets per task */}
      {quickTask && (
        <QuickActionModal
          key={quickTask.id}
          task={quickTask}
          onClose={() => setQuickTask(null)}
          onDone={invalidate}
        />
      )}
    </div>
  )
}
