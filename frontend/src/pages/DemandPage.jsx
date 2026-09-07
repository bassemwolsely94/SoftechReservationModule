/**
 * DemandPage.jsx  —  /demand
 * Demand & Lost Sales Engine — list view + create modal
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { demandApi, branchesApi, usersApi } from '../api/client'
import BranchSelect from '../components/BranchSelect'
import useAuthStore from '../store/authStore'
import CanDo from '../components/CanDo'
import ItemSearchWidget from '../components/ItemSearchWidget'
import CustomerSearchWidget from '../components/CustomerSearchWidget'
import ModuleNotificationBell from '../components/ModuleNotificationBell'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// ── Design tokens ─────────────────────────────────────────────────────────────
const BRAND  = 'rgb(var(--c-brand-600))'
const GREEN  = '#10b981'
const BLUE   = '#3b82f6'
const ORANGE = '#f59e0b'
const RED    = '#ef4444'
const PURPLE = '#8b5cf6'
const GRAY   = '#9ca3af'

// Mirrors apps/demand/models.py DemandRecord.STATUS_CHOICES (9 states).
const STATUS_CFG = {
  new:                { label: 'جديد',           dot: ORANGE, bg: '#fffbeb', text: '#92400e' },
  assigned:           { label: 'مُعيَّن',         dot: BLUE,   bg: '#eff6ff', text: '#1e40af' },
  follow_up:          { label: 'متابعة',          dot: PURPLE, bg: '#f5f3ff', text: '#5b21b6' },
  stock_eta:          { label: 'انتظار المخزون', dot: ORANGE, bg: '#fffbeb', text: '#92400e' },
  transfer_suggested: { label: 'اقتراح تحويل',    dot: PURPLE, bg: '#f5f3ff', text: '#5b21b6' },
  purchasing_flagged: { label: 'للمشتريات',       dot: RED,    bg: '#fff1f2', text: '#9f1239' },
  fulfilled:          { label: 'تم التسليم',       dot: GREEN,  bg: '#f0fdf4', text: '#166534' },
  lost:               { label: 'بيع ضائع',         dot: RED,    bg: '#fef2f2', text: '#991b1b' },
  cancelled:          { label: 'ملغي',             dot: GRAY,   bg: '#f9fafb', text: '#9ca3af' },
}

const PRIORITY_CFG = {
  low:     { label: 'منخفض',           cls: 'bg-gray-100 text-gray-500'   },
  normal:  { label: 'عادي',            cls: 'bg-blue-100 text-blue-700'   },
  high:    { label: 'عالٍ',            cls: 'bg-orange-100 text-orange-700' },
  urgent:  { label: 'عاجل 🔴',        cls: 'bg-red-100 text-red-700'     },
  chronic: { label: 'مزمن 💊',        cls: 'bg-purple-100 text-purple-700' },
}

const SOURCE_OPTIONS = [
  { value: 'walk_in',      label: '🚶 حضر للفرع' },
  { value: 'phone',        label: '📞 اتصال' },
  { value: 'whatsapp',     label: '💬 واتساب' },
  { value: 'delivery',     label: '📱 تطبيق توصيل' },
  { value: 'online',       label: '🌐 موقع' },
  { value: 'call_center',  label: '⚙️ مركز الاتصالات' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

// Egyptian phone validation: mobile = 11 digits starting 01 (01003280328);
// landline = area code 0X + 8-digit subscriber number (0225740408).
function validateEgyptPhone(raw) {
  const d = (raw || '').replace(/\D/g, '')
  if (!d) return { valid: false, empty: true }
  const isMobile   = /^01\d{9}$/.test(d)
  const isLandline = /^0[2-9]\d{6,8}$/.test(d)
  return { valid: isMobile || isLandline, empty: false }
}

function timeAgo(d) {
  if (!d) return '—'
  try { return toLatinDigits(formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })) } catch { return '' }
}

function StatusBadge({ status }) {
  const s = STATUS_CFG[status] || STATUS_CFG.new
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold"
      style={{ background: s.bg, color: s.text }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.dot }} />
      {s.label}
    </span>
  )
}

function PriorityBadge({ priority }) {
  const p = PRIORITY_CFG[priority] || PRIORITY_CFG.normal
  return <span className={`badge text-xs ${p.cls}`}>{p.label}</span>
}

function SlaChip({ breached, minsRemaining }) {
  if (breached) {
    return <span className="badge text-xs bg-red-100 text-red-700">⚠ SLA تجاوز</span>
  }
  // Only warn when the deadline is close (SLA applies to new/assigned states).
  if (minsRemaining != null && minsRemaining >= 0 && minsRemaining <= 10) {
    return <span className="badge text-xs bg-orange-100 text-orange-700">⏱ {Math.round(minsRemaining)}د</span>
  }
  return null
}

// ── Substitutes strip (Phase 3) ───────────────────────────────────────────────
// Shows in-stock same-molecule alternatives for an out-of-stock item at capture.

function SubstitutesStrip({ item, branchId, addedIds, onAdd }) {
  const { data = [] } = useQuery({
    queryKey: ['substitutes', item.id, branchId],
    queryFn: () => demandApi.substitutes({ item: item.id, branch: branchId })
      .then(r => r.data.substitutes || []),
    enabled: !!branchId,
    staleTime: 60_000,
  })
  const subs = (data || []).filter(s => !addedIds.includes(s.id))
  if (!subs.length) return null
  return (
    <div className="mt-1 mr-3 border-r-2 border-blue-200 bg-blue-50/60 rounded-lg px-3 py-2">
      <div className="text-[11px] font-bold text-blue-700 mb-1.5">
        💊 بدائل متوفرة بنفس المادة الفعّالة — حوّل البيع الآن
      </div>
      <div className="flex flex-wrap gap-1.5">
        {subs.map(s => (
          <button key={s.id} type="button" onClick={() => onAdd(s, item.id)}
            className="text-xs bg-white border border-blue-200 rounded-lg px-2 py-1 hover:bg-blue-100 text-blue-800 transition-colors"
            title={`متاح بالفرع: ${s.stock_at_branch} · الشبكة: ${s.stock_network} · ${s.pack_price} ج.م`}>
            + {s.name}
            <span className="text-blue-400 mr-1">({Math.round(s.stock_at_branch || s.stock_network)} متاح)</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Create Demand Modal ───────────────────────────────────────────────────────

function CreateDemandModal({ branches, userBranchId, onClose, onCreated }) {
  const [form, setForm] = useState({
    branch: String(userBranchId || ''),
    contact_phone: '',
    contact_name: '',
    phcode: '',
    source_channel: 'walk_in',
    priority: 'normal',
    notes: '',
  })
  const [items, setItems] = useState([])   // [{item, qty, notes}]
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [selectedCustomer, setSelectedCustomer] = useState(null)

  function f(field) { return e => setForm(prev => ({ ...prev, [field]: e.target.value })) }

  function handleCustomerSelect(c) {
    setSelectedCustomer(c)
    if (!c) return
    setForm(prev => ({
      ...prev,
      contact_phone: c.phone  || prev.contact_phone,
      contact_name:  c.name   || prev.contact_name,
      phcode:        c.softech_pic || prev.phcode,
    }))
  }

  function addItem(item, substituteFor = null) {
    if (items.find(i => i.item && i.item.id === item.id)) return
    setItems(p => [...p, { item, qty: '1', notes: '', substituteFor }])
  }

  // Uncoded item: free-text name + optional hand-entered pack value (flagged manual).
  function addUncoded() {
    setItems(p => [...p, { uncoded: true, name: '', price: '', qty: '1', notes: '' }])
  }

  function removeItem(idx) { setItems(p => p.filter((_, i) => i !== idx)) }

  function updateItem(idx, field, val) {
    setItems(p => p.map((row, i) => i === idx ? { ...row, [field]: val } : row))
  }

  async function handleSubmit() {
    if (!form.contact_phone.trim()) { setError('رقم الهاتف مطلوب'); return }
    if (!validateEgyptPhone(form.contact_phone).valid) {
      setError('رقم الهاتف غير صالح: موبايل 11 رقماً يبدأ بـ 01، أو أرضي بكود المحافظة مثل 02/03'); return
    }
    if (!form.branch)               { setError('اختر الفرع'); return }
    if (items.length === 0)         { setError('أضف صنفاً واحداً على الأقل'); return }
    const noName = items.find(i => i.uncoded && !i.name.trim())
    if (noName) { setError('اكتب اسم الصنف غير المكوَّد'); return }
    const bad = items.find(i => !i.qty || Number(i.qty) <= 0)
    if (bad) { setError(`أدخل الكمية لـ: ${bad.uncoded ? (bad.name || 'الصنف') : bad.item.name}`); return }

    setSubmitting(true); setError('')
    try {
      const res = await demandApi.create({
        phone:         form.contact_phone,
        customer_name: form.contact_name,
        phcode:        form.phcode,
        branch:        Number(form.branch),
        source:        form.source_channel,
        priority:      form.priority,
        notes:         form.notes,
        items: items.map(i => i.uncoded
          ? {
              item_name_free: i.name.trim(),
              quantity: i.qty, notes: i.notes || '',
              manual_price: i.price !== '' ? Number(i.price) : undefined,
            }
          : {
              item: i.item.id, quantity: i.qty, notes: i.notes || '',
              substitute_for_item: i.substituteFor || undefined,
            }),
      })
      onCreated(res.data.id)
      onClose()
    } catch (e) {
      const d = e.response?.data
      setError(typeof d === 'object' ? Object.values(d).flat().join(' — ') : 'حدث خطأ')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[92vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
          <div>
            <h2 className="font-black text-gray-900 text-base">تسجيل طلب عميل جديد</h2>
            <p className="text-xs text-gray-400 mt-0.5">صنف غير متوفر · طلب غير مُستوفى · بيع ضائع محتمل</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl p-1">✕</button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-4 space-y-4">

          {/* Customer identity */}
          <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 space-y-3">
            <div className="text-xs font-bold text-blue-700">هوية العميل</div>

            {/* PIC / Customer search — auto-fills fields below when a known customer is found */}
            <CustomerSearchWidget
              selected={selectedCustomer}
              onSelect={handleCustomerSelect}
              placeholder="ابحث بالاسم أو الهاتف أو كود PIC..."
              allowManual={false}
            />

            {/* Manual override fields — always editable regardless of customer selection */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label text-xs">رقم الهاتف *</label>
                <input
                  className={`input-field ${
                    form.contact_phone && !validateEgyptPhone(form.contact_phone).valid
                      ? 'border-red-300 focus:border-red-400' : ''
                  }`}
                  placeholder="01003280328" dir="ltr"
                  value={form.contact_phone} onChange={f('contact_phone')} />
                {form.contact_phone && !validateEgyptPhone(form.contact_phone).valid && (
                  <p className="text-[11px] text-red-500 mt-1 leading-snug">
                    ⚠ رقم غير صالح. موبايل: 11 رقماً يبدأ بـ 01 (مثال 01003280328).
                    أرضي: كود المحافظة مثل 02/03 (مثال 0225740408).
                  </p>
                )}
              </div>
              <div>
                <label className="label text-xs">الاسم</label>
                <input className="input-field" placeholder="اسم العميل"
                  value={form.contact_name} onChange={f('contact_name')} />
              </div>
            </div>
            <div>
              <label className="label text-xs">كود العميل PIC (اختياري)</label>
              <input className="input-field font-mono text-sm" placeholder="مثال: 140HD515"
                dir="ltr" value={form.phcode} onChange={f('phcode')} />
              <p className="text-xs text-blue-500 mt-1">
                اختر عميلاً من البحث أعلاه ليتم ملء الحقول تلقائياً، أو أدخلها يدوياً
              </p>
            </div>
          </div>

          {/* Branch + source + priority */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="label text-xs">الفرع *</label>
              <BranchSelect
                value={form.branch}
                onChange={v => setForm(prev => ({ ...prev, branch: v }))}
                branches={branches || []}
                placeholder="اختر الفرع..."
              />
            </div>
            <div>
              <label className="label text-xs">مصدر الطلب</label>
              <select className="input-field" value={form.source_channel} onChange={f('source_channel')}>
                {SOURCE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label text-xs">الأولوية</label>
              <select className="input-field" value={form.priority} onChange={f('priority')}>
                {Object.entries(PRIORITY_CFG).map(([v, c]) => (
                  <option key={v} value={v}>{c.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Items */}
          <div>
            <label className="label text-xs mb-2">الأصناف المطلوبة *</label>
            {/* Pass selected=null always so widget resets after each pick (items go to the list below) */}
            <ItemSearchWidget
              selected={null}
              onSelect={addItem}
              onClear={() => {}}
              placeholder="ابحث باسم الصنف أو الكود أو الباركود (قارئ ضوئي متوافق)..."
            />
            <button type="button" onClick={addUncoded}
              className="mt-2 text-xs text-brand-600 hover:text-brand-700 font-semibold">
              + إضافة صنف غير مكوَّد (يدوي)
            </button>
          </div>

          {items.length === 0 ? (
            <div className="border-2 border-dashed border-gray-200 rounded-xl py-6 text-center">
              <div className="text-3xl mb-1">💊</div>
              <div className="text-sm text-gray-400">ابحث عن صنف أعلاه، أو أضف صنفاً غير مكوَّد يدوياً</div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs font-bold text-gray-500">الأصناف المضافة ({items.length})</div>
              {items.map((row, idx) => row.uncoded ? (
                /* ── Uncoded (manual) item ── */
                <div key={`u-${idx}`}
                  className="bg-amber-50 border border-amber-200 rounded-xl px-3 py-2.5 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="badge bg-amber-100 text-amber-700 text-[10px] shrink-0">✋ يدوي · غير مكوَّد</span>
                    <input placeholder="اسم الصنف (نص حر)" value={row.name}
                      onChange={e => updateItem(idx, 'name', e.target.value)}
                      className="flex-1 min-w-0 border border-amber-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-amber-400" />
                    <button onClick={() => removeItem(idx)}
                      className="text-gray-300 hover:text-red-400 text-xl leading-none shrink-0">✕</button>
                  </div>
                  <div className="flex items-center gap-2">
                    <input type="number" min="0.001" step="0.001" placeholder="كمية"
                      value={row.qty} onChange={e => updateItem(idx, 'qty', e.target.value)}
                      className="w-20 border border-amber-200 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:border-amber-400" />
                    <div className="flex items-center gap-1">
                      <input type="number" min="0" step="0.01" placeholder="سعر العبوة (تقديري)"
                        value={row.price} onChange={e => updateItem(idx, 'price', e.target.value)}
                        className="w-36 border border-amber-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-amber-400" />
                      <span className="text-[10px] text-amber-600">ج.م · تقديري</span>
                    </div>
                    <input placeholder="ملاحظة" value={row.notes}
                      onChange={e => updateItem(idx, 'notes', e.target.value)}
                      className="flex-1 min-w-0 border border-amber-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-amber-400" />
                  </div>
                  <p className="text-[10px] text-amber-600">
                    قيمة مُدخَلة يدوياً وغير مؤكدة — لم تُجلب من نظام ERP.
                  </p>
                </div>
              ) : (
                /* ── Coded (ERP) item ── */
                <div key={row.item.id}>
                  <div className="flex items-center gap-3 bg-gray-50 border border-gray-200 rounded-xl px-3 py-2.5">
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-gray-800 text-sm flex items-center gap-1.5 flex-wrap">
                        <span className="break-words">{row.item.name}</span>
                        {row.substituteFor && (
                          <span className="badge bg-blue-100 text-blue-700 text-[10px]">بديل علمي</span>
                        )}
                      </div>
                      <div className="text-xs text-blue-500 font-mono">كود: {row.item.softech_id}</div>
                    </div>
                    <input type="number" min="0.001" step="0.001" placeholder="كمية"
                      value={row.qty} onChange={e => updateItem(idx, 'qty', e.target.value)}
                      className="w-20 border border-gray-200 rounded-lg px-2 py-1 text-sm text-center focus:outline-none focus:border-brand-400" />
                    <input placeholder="ملاحظة" value={row.notes}
                      onChange={e => updateItem(idx, 'notes', e.target.value)}
                      className="w-28 border border-gray-200 rounded-lg px-2 py-1 text-xs focus:outline-none focus:border-brand-400" />
                    <button onClick={() => removeItem(idx)}
                      className="text-gray-300 hover:text-red-400 text-xl leading-none">✕</button>
                  </div>
                  {!row.substituteFor && (
                    <SubstitutesStrip
                      item={row.item}
                      branchId={form.branch}
                      addedIds={items.filter(i => i.item).map(i => i.item.id)}
                      onAdd={(sub, forId) => addItem(sub, forId)} />
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Notes */}
          <div>
            <label className="label text-xs">ملاحظات</label>
            <textarea rows={2} className="input-field resize-none text-sm"
              placeholder="أي تفاصيل إضافية..."
              value={form.notes} onChange={f('notes')} />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t flex-shrink-0 flex items-center justify-between gap-3">
          <div className="text-xs text-gray-400">
            {items.length > 0
              ? `${items.length} صنف · سيتم البحث عن العميل في الـ ERP تلقائياً`
              : 'أضف أصناف للمتابعة'}
          </div>
          <div className="flex gap-2">
            <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
            <button onClick={handleSubmit}
              disabled={submitting || items.length === 0}
              className="btn-primary text-sm disabled:opacity-50">
              {submitting ? 'جارٍ...' : '📋 تسجيل الطلب'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Demand Row ────────────────────────────────────────────────────────────────

function DemandRow({ demand, onClick, selected, onToggle }) {
  const s = STATUS_CFG[demand.status] || STATUS_CFG.new
  const p = PRIORITY_CFG[demand.priority] || PRIORITY_CFG.normal
  return (
    <tr onClick={onClick}
      className={`cursor-pointer hover:bg-brand-50 transition-colors border-b border-gray-50 last:border-0 ${selected ? 'bg-brand-50/60' : ''}`}>
      <td className="px-3 py-3" onClick={e => e.stopPropagation()}>
        <input type="checkbox" className="w-4 h-4 accent-brand-600 cursor-pointer"
          checked={selected} onChange={() => onToggle(demand.id)} />
      </td>
      <td className="px-4 py-3">
        <div className="font-bold text-brand-700 font-mono text-sm">{demand.demand_number}</div>
        <div className="text-xs text-gray-400 mt-0.5">{timeAgo(demand.created_at)}</div>
      </td>
      <td className="px-4 py-3">
        <div className="font-semibold text-gray-800 text-sm">{demand.customer_name || '—'}</div>
        <div className="text-xs text-gray-500 font-mono" dir="ltr">{demand.phone}</div>
        {demand.phcode && (
          <div className="text-xs text-blue-400 font-mono mt-0.5">{demand.phcode}</div>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-gray-600">{demand.branch_name}</td>
      <td className="px-4 py-3 text-xs text-gray-500 tabular-nums">{demand.total_items} صنف</td>
      <td className="px-4 py-3">
        <StatusBadge status={demand.status} />
      </td>
      <td className="px-4 py-3">
        <span className={`badge text-xs ${p.cls}`}>{p.label}</span>
      </td>
      <td className="px-4 py-3">
        <SlaChip breached={demand.sla_breached} minsRemaining={demand.sla_minutes_remaining} />
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">{demand.assigned_name || '—'}</td>
    </tr>
  )
}

// ── Bulk action bar ────────────────────────────────────────────────────────────

function BulkBar({ count, staff, busy, onAssign, onFlag, onCancel, onClear }) {
  const [assignee, setAssignee] = useState('')
  return (
    <div className="flex items-center gap-2 bg-brand-50 border border-brand-200 rounded-xl px-4 py-2.5 mb-3 flex-wrap">
      <span className="text-sm font-bold text-brand-700">{count} طلب محدد</span>
      <div className="flex-1" />
      <CanDo module="demand" action="assign">
        <select className="input-field text-xs w-44" value={assignee} onChange={e => setAssignee(e.target.value)}>
          <option value="">تعيين إلى...</option>
          {staff.map(s => (
            <option key={s.id} value={s.id}>{s.full_name || s.username || `#${s.id}`}</option>
          ))}
        </select>
        <button disabled={!assignee || busy} onClick={() => onAssign(Number(assignee))}
          className="btn-secondary text-xs px-3 disabled:opacity-50">تعيين</button>
      </CanDo>
      <CanDo module="demand" action="edit">
        <button disabled={busy} onClick={onFlag}
          className="btn-secondary text-xs px-3 disabled:opacity-50">📦 إرسال للمشتريات</button>
      </CanDo>
      <CanDo module="demand" action="delete">
        <button disabled={busy} onClick={onCancel}
          className="text-xs px-3 py-1.5 rounded-lg bg-red-50 text-red-600 hover:bg-red-100 disabled:opacity-50">إلغاء</button>
      </CanDo>
      <button onClick={onClear} className="text-xs text-gray-400 hover:text-gray-600 px-2">مسح التحديد</button>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DemandPage() {
  const navigate      = useNavigate()
  const qc            = useQueryClient()
  const { user }      = useAuthStore()

  const [showCreate, setShowCreate] = useState(false)
  const [filters, setFilters] = useState({
    status: '', priority: '', branch: '', search: '', sla_breached: '',
  })

  const [searchInput, setSearchInput] = useState('')

// Debounce search
useEffect(() => {
  const delay = setTimeout(() => {
    setFilters(f => ({ ...f, search: searchInput }))
  }, 400)

  return () => clearTimeout(delay)
}, [searchInput])

  const isCCOrAdmin   = ['admin', 'call_center', 'purchasing'].includes(user?.role)
  const userBranchId  = user?.branch_id

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })

  // Open back-in-stock recovery opportunities (badge on the recovery tab)
  const { data: recKpis } = useQuery({
    queryKey: ['demand-dashboard-kpis'],
    queryFn: () => demandApi.dashboard().then(r => r.data?.kpis || {}),
    refetchInterval: 120_000,
  })
  const openRecovery = recKpis?.open_recovery_count ?? 0

  const { data: demands = [], isLoading } = useQuery({
    queryKey: [
  'demands',
  filters.status,
  filters.priority,
  filters.branch,
  filters.search,
  filters.sla_breached,
],
    queryFn: () => demandApi.list({
      status:       filters.status       || undefined,
      priority:     filters.priority     || undefined,
      branch:       filters.branch       || undefined,
      search:       filters.search       || undefined,
    }).then(r => r.data.results || r.data),
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  })

  // sla_breached is a computed property, not a DB filter — apply it client-side.
  const visibleDemands = filters.sla_breached === 'true'
    ? demands.filter(d => d.sla_breached)
    : demands

  // ── Bulk selection ──────────────────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = useState([])
  const [bulkBusy, setBulkBusy] = useState(false)
  const toggleId  = id => setSelectedIds(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])
  const allVisibleIds = visibleDemands.map(d => d.id)
  const allSelected = allVisibleIds.length > 0 && allVisibleIds.every(id => selectedIds.includes(id))
  const toggleAll = () => setSelectedIds(allSelected ? [] : allVisibleIds)

  const { data: staffList = [] } = useQuery({
    queryKey: ['assignable-staff'],
    queryFn: () => usersApi.list({ is_active: true }).then(r => r.data.results || r.data),
    staleTime: 300_000,
  })

  async function doBulk(action, assigned_to) {
    if (action === 'cancel' && !window.confirm(`إلغاء ${selectedIds.length} طلب؟`)) return
    setBulkBusy(true)
    try {
      const { data } = await demandApi.bulkAction({ ids: selectedIds, action, assigned_to })
      qc.invalidateQueries(['demands'])
      setSelectedIds([])
      if (data.skipped) alert(`تم: ${data.ok} · تم تخطّي ${data.skipped} (حالة غير صالحة للإجراء)`)
    } catch (e) {
      alert(e.response?.data?.detail || 'تعذّر تنفيذ الإجراء')
    } finally { setBulkBusy(false) }
  }

  const activeCount  = demands.filter(d => !['fulfilled', 'lost', 'cancelled'].includes(d.status)).length
  const lostCount    = demands.filter(d => d.status === 'lost').length
  const breachCount  = demands.filter(d => d.sla_breached).length

  const TAB_FILTERS = [
    { label: 'الكل',             value: '' },
    { label: 'جديد',            value: 'new' },
    { label: 'مُعيَّن',         value: 'assigned' },
    { label: 'متابعة',          value: 'follow_up' },
    { label: 'انتظار المخزون',  value: 'stock_eta' },
    { label: 'للمشتريات',       value: 'purchasing_flagged' },
    { label: 'بيع ضائع',        value: 'lost' },
    { label: 'تم التسليم',       value: 'fulfilled' },
  ]

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center gap-4 flex-wrap">
            <div>
              <h1 className="text-lg font-black text-gray-900">طلبات العملاء والطلب الضائع</h1>
              <p className="text-xs text-gray-400 mt-0.5">
                {demands.length} طلب إجمالي
                {activeCount  > 0 && <span className="text-brand-600 mr-2">· {activeCount} نشط</span>}
                {lostCount    > 0 && <span className="text-red-600 mr-2">· {lostCount} بيع ضائع</span>}
                {breachCount  > 0 && <span className="text-red-600 font-bold mr-2">· {breachCount} ⚠ SLA تجاوز</span>}
              </p>
            </div>
            <div className="flex-1" />
            <CanDo module="demand" action="view">
              <ModuleNotificationBell category="demand" label="إشعارات الطلب الضائع" />
            </CanDo>
            <button
              onClick={() => navigate('/demand/recovery')}
              className="btn-secondary text-sm relative">
              🔔 عاد للمخزون
              {openRecovery > 0 && (
                <span className="absolute -top-2 -left-2 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
                  {openRecovery}
                </span>
              )}
            </button>
            <button
              onClick={() => navigate('/demand/dashboard')}
              className="btn-secondary text-sm">
              📊 لوحة الطلب الضائع
            </button>
            <CanDo module="demand" action="create">
              <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
                + تسجيل طلب جديد
              </button>
            </CanDo>
          </div>

          {/* Status tab strip */}
          <div className="flex gap-1 mt-3 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
            {TAB_FILTERS.map(t => (
              <button key={t.value}
                onClick={() => setFilters(p => ({ ...p, status: t.value }))}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
                  filters.status === t.value
                    ? 'text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
                style={filters.status === t.value ? { background: BRAND } : {}}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Search + filters row */}
          <div className="flex gap-2 mt-2 flex-wrap">
            <input className="input-field w-52 text-xs"
  placeholder="🔍 بحث بالهاتف، اسم العميل، PIC، الصنف..."
  value={searchInput}
  onChange={e => setSearchInput(e.target.value)}
/>
            <select className="input-field w-36 text-xs" value={filters.priority}
              onChange={e => setFilters(p => ({ ...p, priority: e.target.value }))}>
              <option value="">كل الأولويات</option>
              {Object.entries(PRIORITY_CFG).map(([v, c]) => (
                <option key={v} value={v}>{c.label}</option>
              ))}
            </select>
            {isCCOrAdmin && (
              <BranchSelect
                size="sm"
                value={filters.branch}
                onChange={v => setFilters(p => ({ ...p, branch: v }))}
                branches={branches}
                allLabel="كل الفروع"
                className="w-52"
              />
            )}
            <select className="input-field w-40 text-xs" value={filters.sla_breached}
              onChange={e => setFilters(p => ({ ...p, sla_breached: e.target.value }))}>
              <option value="">كل الطلبات</option>
              <option value="true">⚠ SLA تجاوز فقط</option>
            </select>
            <button className="btn-secondary text-xs px-3"
  onClick={() => {
    setFilters({ status: '', priority: '', branch: '', search: '', sla_breached: '' })
    setSearchInput('')
  }}>
              مسح
            </button>
          </div>
        </div>
      </div>

      {/* List */}
      <div className="max-w-7xl mx-auto px-6 py-5">
        {isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[1,2,3,4,5].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl" />)}
          </div>
        ) : visibleDemands.length === 0 ? (
          <div className="card text-center py-16">
            <div className="text-5xl mb-3">📋</div>
            <div className="text-gray-600 font-semibold">
              {filters.status || filters.search || filters.sla_breached ? 'لا توجد نتائج' : 'لا توجد طلبات بعد'}
            </div>
            <div className="text-gray-400 text-xs mt-1 mb-5">
              {!filters.status && !filters.search && 'اضغط "+ تسجيل طلب جديد" لبدء تتبع الطلب الضائع'}
            </div>
            {!filters.status && !filters.search && (
              <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
                + تسجيل طلب جديد
              </button>
            )}
          </div>
        ) : (
          <>
            {selectedIds.length > 0 && (
              <BulkBar
                count={selectedIds.length}
                staff={staffList}
                busy={bulkBusy}
                onAssign={(id) => doBulk('assign', id)}
                onFlag={() => doBulk('flag_purchasing')}
                onCancel={() => doBulk('cancel')}
                onClear={() => setSelectedIds([])}
              />
            )}
          <div className="card p-0 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="px-3 py-3 w-10">
                      <input type="checkbox" className="w-4 h-4 accent-brand-600 cursor-pointer"
                        checked={allSelected} onChange={toggleAll} />
                    </th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">رقم الطلب</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">العميل</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الفرع</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الأصناف</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الحالة</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الأولوية</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">SLA</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">مُعيَّن لـ</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleDemands.map(d => (
                    <DemandRow key={d.id} demand={d}
                      selected={selectedIds.includes(d.id)}
                      onToggle={toggleId}
                      onClick={() => navigate(`/demand/${d.id}`)} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          </>
        )}
      </div>

      {showCreate && (
        <CreateDemandModal
          branches={branches}
          userBranchId={userBranchId}
          onClose={() => setShowCreate(false)}
          onCreated={(id) => {
            qc.invalidateQueries(['demands'])
            navigate(`/demand/${id}`)
          }}
        />
      )}
    </div>
  )
}
