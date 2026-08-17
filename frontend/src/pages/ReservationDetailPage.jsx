import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reservationsApi, configApi, demandApi } from '../api/client'
import { StatusBadge, PriorityBadge, STATUS_OPTIONS } from '../components/StatusBadge'
import useAuthStore from '../store/authStore'
import { format, formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
import PrintReceiptModal from '../components/PrintReceiptModal'
import WhatsAppShareButton from '../components/WhatsAppShareButton'
import VoiceNoteRecorder from '../components/VoiceNoteRecorder'
import CanDo from '../components/CanDo'
import ItemSearchWidget from '../components/ItemSearchWidget'

// ── Constants ─────────────────────────────────────────────────────────────────

const ORDER_SOURCE_LABELS = {
  cc_whatsapp:     'كول سنتر — واتساب',
  cc_call:         'كول سنتر — مكالمة',
  branch_whatsapp: 'الفرع — واتساب',
  branch_call:     'الفرع — مكالمة',
  online:          'طلب إلكتروني',
}
const FULFILLMENT_LABELS = {
  pickup:   'استلام من الفرع',
  delivery: 'توصيل',
}

const NEXT_STATUSES = {
  pending:   ['available', 'cancelled'],
  available: ['contacted', 'cancelled'],
  contacted: ['confirmed', 'expired', 'cancelled'],
  confirmed: ['fulfilled', 'cancelled'],
  fulfilled: [],
  cancelled: [],
  expired:   [],
}

const ACTIVITY_TYPE_OPTIONS = [
  { value: 'note',               label: '📝 ملاحظة' },
  { value: 'call_made',          label: '📞 مكالمة أُجريت' },
  { value: 'customer_replied',   label: '💬 رد العميل' },
  { value: 'stock_checked',      label: '🔍 تم فحص المخزون' },
  { value: 'transfer_requested', label: '🔀 طلب تحويل مخزون' },
]

const STATUS_COLOR_MAP = {
  pending:   { bg: 'bg-gray-100',   text: 'text-gray-700',   dot: '#9ca3af' },
  available: { bg: 'bg-orange-100', text: 'text-orange-700', dot: '#f59e0b' },
  contacted: { bg: 'bg-blue-100',   text: 'text-blue-700',   dot: '#3b82f6' },
  confirmed: { bg: 'bg-indigo-100', text: 'text-indigo-700', dot: '#6366f1' },
  fulfilled: { bg: 'bg-green-100',  text: 'text-green-700',  dot: '#10b981' },
  cancelled: { bg: 'bg-red-100',    text: 'text-red-700',    dot: '#ef4444' },
  expired:   { bg: 'bg-red-100',    text: 'text-red-700',    dot: '#ef4444' },
}

const ROLE_ACTIONS = {
  call_center: [
    { status: 'available', label: 'المخزون متاح 📦' },
    { status: 'contacted', label: 'تم التواصل 📞' },
    { status: 'cancelled', label: 'إلغاء الحجز ✕' },
  ],
  pharmacist: [
    { status: 'confirmed', label: 'العميل قادم ✅' },
    { status: 'fulfilled', label: 'تم الصرف 💊' },
    { status: 'cancelled', label: 'إلغاء ✕' },
  ],
  salesperson: [
    { status: 'available', label: 'المخزون متاح 📦' },
    { status: 'contacted', label: 'تم التواصل 📞' },
    { status: 'cancelled', label: 'إلغاء ✕' },
  ],
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(dt) {
  try { return toLatinDigits(formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true })) } catch { return '' }
}

function formatDate(d) {
  if (!d) return '—'
  try { return toLatinDigits(format(new Date(d), 'd MMMM yyyy', { locale: ar })) } catch { return d }
}

function formatDateTime(d) {
  if (!d) return '—'
  try { return toLatinDigits(format(new Date(d), 'd MMM yyyy — HH:mm', { locale: ar })) } catch { return d }
}

// ── Customer-facing helpers ────────────────────────────────────────────────────

/**
 * Normalise an Egyptian phone number to E.164 digits (no +) for wa.me.
 * Handles:  01xxxxxxxxx  →  2001xxxxxxxxx
 *           +2001…       →  2001…
 *           2001…        →  2001…  (already good)
 */
function toWhatsAppPhone(raw) {
  if (!raw) return null
  let p = raw.replace(/[\s\-().]/g, '')
  if (p.startsWith('+')) p = p.slice(1)
  if (p.startsWith('00')) p = p.slice(2)
  if (p.startsWith('0')) p = '20' + p.slice(1)
  if (!p.startsWith('20')) p = '20' + p
  return p
}

/** Collect primary item + all extra lines into a flat array for messaging/print. */
function getAllReservationItems(r) {
  const items = []
  if (r.item_name || r.manual_item_name) {
    items.push({
      name: r.item_name || r.manual_item_name || '—',
      softech_id: r.item_softech_id || null,
      quantity: r.quantity_requested,
      item_id: r.item || null,
    })
  }
  if (r.lines?.length) {
    r.lines.forEach(l => items.push({
      name: l.item_name || '—',
      softech_id: l.item_softech_id || null,
      quantity: l.quantity_requested,
      item_id: l.item || null,
    }))
  }
  return items
}

/**
 * Build the Arabic WhatsApp confirmation message (no prices, customer-safe).
 * pharmacy — from GET /api/config/pharmacy/ (optional, gracefully skipped if null)
 */
function buildCustomerWhatsAppText(r, pharmacy = null) {
  const pharmacyName = pharmacy?.name_ar || 'صيدليات الرزيقي'
  const allItems = getAllReservationItems(r)
  const lines = [
    `${pharmacyName} 🏥`,
    '',
    `عزيزي/عزيزتي ${r.contact_name || ''}،`,
    '',
    '✅ تم تسجيل طلب حجزكم بنجاح',
    '',
    '📋 تفاصيل الطلب:',
  ]

  if (allItems.length === 1) {
    const it = allItems[0]
    lines.push(`• الصنف: ${it.name}`)
    if (it.softech_id) lines.push(`• الكود: ${it.softech_id}`)
    lines.push(`• الكمية المطلوبة: ${it.quantity}`)
  } else {
    lines.push(`• الأصناف المطلوبة (${allItems.length} صنف):`)
    allItems.forEach((it, i) => {
      const code = it.softech_id ? ` [${it.softech_id}]` : ''
      lines.push(`  ${i + 1}. ${it.name}${code} × ${it.quantity}`)
    })
  }

  if (r.branch_name)           lines.push(`• الفرع: ${r.branch_name}`)
  lines.push(`• رقم الحجز: #${r.id}`)
  if (r.expected_arrival_date) lines.push(`• موعد التوفر المتوقع: ${formatDate(r.expected_arrival_date)}`)
  lines.push('')
  lines.push('سنتواصل معكم فور توفر الصنف.')
  lines.push('شكراً لثقتكم 🙏')

  // Pharmacy contact footer
  if (pharmacy) {
    lines.push('')
    lines.push('─'.repeat(20))
    lines.push(`📍 *${pharmacyName}*`)
    if (pharmacy.call_center_numbers?.length) {
      pharmacy.call_center_numbers.forEach(n => lines.push(`📞 ${n}`))
    }
    if (pharmacy.website)         lines.push(`🌐 ${pharmacy.website}`)
    if (pharmacy.whatsapp_number) lines.push(`💬 واتساب: https://wa.me/${pharmacy.whatsapp_number}`)
    if (pharmacy.branches?.length) {
      lines.push('')
      lines.push('🏪 *فروعنا:*')
      pharmacy.branches.forEach(b => {
        const name  = b.name_ar || b.name
        const phone = b.phone ? ` — ${b.phone}` : ''
        const addr  = b.address ? `\n   📍 ${b.address}` : ''
        lines.push(`• ${name}${phone}${addr}`)
      })
    }
    if (pharmacy.extra_footer_ar) lines.push(`\n${pharmacy.extra_footer_ar}`)
  }

  return lines.join('\n')
}

/**
 * Open a new window, write a clean Arabic customer receipt, and trigger print.
 * No prices, no internal fields — customer-safe content only.
 * pharmacy — from GET /api/config/pharmacy/ (optional)
 */
function printCustomerReceipt(r, pharmacy = null) {
  const fulfillmentLabel = r.fulfillment_method === 'delivery' ? 'توصيل للمنزل'
    : r.fulfillment_method === 'pickup' ? 'استلام من الفرع' : null

  const pharmacyName = pharmacy?.name_ar || 'صيدليات الرزيقي'
  const pharmacyEn   = pharmacy?.name_en  || 'ElRezeiky Pharmacies'
  const tagline      = pharmacy?.tagline_ar || ''

  // Build call-center numbers line
  const phoneLines = (pharmacy?.call_center_numbers || [])
    .map(n => `<div>📞 <strong dir="ltr">${n}</strong></div>`).join('')

  // Build branches list
  const branchLines = (pharmacy?.branches || []).map(b => `
    <div class="branch-row">
      <span class="branch-name">${b.name_ar || b.name}</span>
      ${b.phone   ? `<span class="branch-phone" dir="ltr">${b.phone}</span>` : ''}
    </div>
    ${b.address   ? `<div class="branch-addr">📍 ${b.address}</div>` : ''}
  `).join('')

  // QR code pointing to main WhatsApp number
  const qrHTML = pharmacy?.whatsapp_number ? `
    <div class="qr-wrap">
      <div class="qr-hint">امسح للتواصل عبر واتساب</div>
      <img
        src="https://api.qrserver.com/v1/create-qr-code/?size=90x90&data=https%3A%2F%2Fwa.me%2F${pharmacy.whatsapp_number}&bgcolor=ffffff&color=059669&margin=3"
        width="90" height="90" alt="QR واتساب"
        class="qr-img"
      />
      <div class="qr-num" dir="ltr">${pharmacy.whatsapp_number}</div>
    </div>` : ''

  const extraFooter = pharmacy?.extra_footer_ar
    ? `<div class="extra-footer">${pharmacy.extra_footer_ar}</div>` : ''

  const allItems = getAllReservationItems(r)

  // Build items HTML for receipt
  const itemsHTML = allItems.length === 1
    ? `<div class="item-name">${allItems[0].name}</div>
       ${allItems[0].softech_id ? `<div class="row"><span class="lbl">الكود</span><span class="val" dir="ltr">${allItems[0].softech_id}</span></div>` : ''}
       <div class="row"><span class="lbl">الكمية</span><span class="val">${allItems[0].quantity} وحدة</span></div>`
    : `<table class="items-table">
         <thead><tr><th>الصنف</th><th>الكود</th><th>الكمية</th></tr></thead>
         <tbody>${allItems.map(it => `
           <tr>
             <td class="item-cell">${it.name}</td>
             <td class="code-cell" dir="ltr">${it.softech_id || '—'}</td>
             <td class="qty-cell">${it.quantity}</td>
           </tr>`).join('')}
         </tbody>
       </table>`

  const w = window.open('', '_blank', 'width=420,height=750')
  if (!w) { alert('يرجى السماح بالنوافذ المنبثقة لطباعة الإيصال'); return }
  w.document.write(`<!DOCTYPE html>
<html dir="rtl" lang="ar-u-nu-latn">
<head>
  <meta charset="UTF-8">
  <title>إيصال حجز #${r.id}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;900&display=swap');
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Cairo',sans-serif;padding:24px;color:#111;font-size:13px;max-width:390px;margin:auto}
    .hdr{text-align:center;border-bottom:2px solid #059669;padding-bottom:14px;margin-bottom:18px}
    .pharmacy{font-size:22px;font-weight:900;color:#059669}
    .pharmacy-en{font-size:11px;color:#6b7280;margin-top:2px}
    .tagline{font-size:11px;color:#6b7280;margin-top:2px}
    .subtitle{font-size:13px;font-weight:600;color:#374151;margin-top:4px}
    .docnum{font-size:11px;color:#9ca3af;margin-top:3px}
    .sec{margin-bottom:16px}
    .sec-title{font-size:10px;letter-spacing:.06em;color:#9ca3af;text-transform:uppercase;border-bottom:1px solid #e5e7eb;padding-bottom:4px;margin-bottom:8px}
    .row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px}
    .lbl{color:#6b7280;font-size:12px}
    .val{font-weight:700;color:#111;font-size:13px;text-align:left}
    .item-name{font-size:14px;font-weight:700;color:#111;margin-bottom:6px;line-height:1.4}
    .footer{margin-top:16px;border-top:1px dashed #d1d5db;padding-top:14px;font-size:11px;color:#555;line-height:2}
    .footer-name{font-size:13px;font-weight:800;color:#059669;text-align:center;margin-bottom:6px}
    .footer-phones{text-align:center;margin-bottom:4px}
    .footer-web{text-align:center;margin-bottom:6px;font-weight:600}
    .branches-title{font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;margin:8px 0 4px}
    .branch-row{display:flex;justify-content:space-between;border-bottom:1px dotted #e5e7eb;padding:3px 0;font-size:11px}
    .branch-name{font-weight:600;color:#374151}
    .branch-phone{color:#6b7280}
    .branch-addr{font-size:10px;color:#9ca3af;margin-bottom:4px}
    .qr-wrap{text-align:center;margin-top:10px}
    .qr-hint{font-size:10px;color:#9ca3af;margin-bottom:4px}
    .qr-img{border:1px solid #d1fae5;border-radius:6px}
    .qr-num{font-size:10px;color:#6b7280;margin-top:3px;font-family:monospace}
    .extra-footer{text-align:center;font-style:italic;font-size:11px;color:#9ca3af;margin-top:8px}
    .badge{display:inline-block;background:#ecfdf5;color:#059669;border:1px solid #a7f3d0;border-radius:6px;font-size:10px;font-weight:700;padding:2px 8px;margin-top:6px}
    .thanks{text-align:center;margin-top:8px;font-size:12px;color:#374151}
    .items-table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:4px}
    .items-table th{text-align:right;font-size:10px;color:#9ca3af;border-bottom:1px solid #e5e7eb;padding:3px 4px;font-weight:600}
    .items-table td{padding:4px;border-bottom:1px dotted #e5e7eb;vertical-align:top}
    .item-cell{font-weight:600;color:#111;line-height:1.3}
    .code-cell{font-family:monospace;color:#6b7280;font-size:10px;white-space:nowrap}
    .qty-cell{font-weight:700;color:#059669;text-align:center;white-space:nowrap}
    @media print{body{padding:8px}@page{size:auto;margin:6mm}}
  </style>
</head>
<body>
  <div class="hdr">
    <div class="pharmacy">${pharmacyName}</div>
    <div class="pharmacy-en">${pharmacyEn}</div>
    ${tagline ? `<div class="tagline">${tagline}</div>` : ''}
    <div class="subtitle">تأكيد طلب حجز</div>
    <div class="docnum">رقم الحجز: #${r.id} &nbsp;·&nbsp; ${formatDate(r.created_at)}</div>
  </div>

  <div class="sec">
    <div class="sec-title">بيانات العميل</div>
    <div class="row"><span class="lbl">الاسم</span><span class="val">${r.contact_name || '—'}</span></div>
    <div class="row"><span class="lbl">الهاتف</span><span class="val" dir="ltr">${r.contact_phone || '—'}</span></div>
  </div>

  <div class="sec">
    <div class="sec-title">الأصناف المطلوبة${allItems.length > 1 ? ` (${allItems.length} صنف)` : ''}</div>
    ${itemsHTML}
  </div>

  <div class="sec">
    <div class="sec-title">تفاصيل التسليم</div>
    ${r.branch_name ? `<div class="row"><span class="lbl">الفرع</span><span class="val">${r.branch_name}</span></div>` : ''}
    ${fulfillmentLabel ? `<div class="row"><span class="lbl">طريقة الاستلام</span><span class="val">${fulfillmentLabel}</span></div>` : ''}
    ${r.expected_arrival_date ? `<div class="row"><span class="lbl">موعد التوفر المتوقع</span><span class="val">${formatDate(r.expected_arrival_date)}</span></div>` : ''}
  </div>

  <div class="footer">
    <div class="thanks">سيتم التواصل معكم فور توفر الصنف<br>شكراً لثقتكم 🙏 <span class="badge">✅ طلب مسجل</span></div>

    <div class="footer-name">${pharmacyName}</div>
    ${phoneLines ? `<div class="footer-phones">${phoneLines}</div>` : ''}
    ${pharmacy?.website ? `<div class="footer-web">🌐 ${pharmacy.website}</div>` : ''}

    ${branchLines ? `<div class="branches-title">فروعنا</div>${branchLines}` : ''}

    ${qrHTML}
    ${extraFooter}
  </div>
</body>
</html>`)
  w.document.close()
  w.focus()
  setTimeout(() => { w.print() }, 800)
}

function InitialsAvatar({ name, role }) {
  const initials = (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('')
  const colors = {
    admin: 'bg-red-500',
    call_center: 'bg-blue-500',
    pharmacist: 'bg-green-600',
    salesperson: 'bg-indigo-500',
    purchasing: 'bg-yellow-600',
  }
  const bg = colors[role] || 'bg-gray-500'
  return (
    <div className={`w-8 h-8 rounded-full ${bg} flex items-center justify-center text-white text-xs font-bold flex-shrink-0`}>
      {initials}
    </div>
  )
}

// ── Stock Widget ──────────────────────────────────────────────────────────────

function StockWidget({ stockByBranch, currentBranchId }) {
  if (!stockByBranch || stockByBranch.length === 0) {
    return (
      <div className="text-xs text-gray-400 text-center py-3">
        لا توجد بيانات مخزون متاحة
      </div>
    )
  }

  const total = stockByBranch.reduce((sum, s) => sum + s.quantity, 0)

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
        <span>الفرع</span>
        <span>الكمية المتاحة</span>
      </div>
      {stockByBranch.map(s => {
        const isCurrent = s.branch_id === currentBranchId
        const pct = total > 0 ? Math.round((s.quantity / total) * 100) : 0
        const barColor = s.quantity > 10
          ? 'bg-green-400'
          : s.quantity > 0
          ? 'bg-orange-400'
          : 'bg-red-300'

        return (
          <div key={s.branch_id} className={`rounded-lg p-2 ${isCurrent ? 'bg-brand-50 border border-brand-200' : 'bg-gray-50'}`}>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                {isCurrent && (
                  <span className="w-1.5 h-1.5 rounded-full bg-brand-500 inline-block" />
                )}
                <span className={`text-xs font-medium ${isCurrent ? 'text-brand-700' : 'text-gray-600'}`}>
                  {s.branch_name}
                </span>
              </div>
              <span className={`text-xs font-bold tabular-nums ${
                s.quantity > 0 ? 'text-green-700' : 'text-red-500'
              }`}>
                {s.quantity > 0 ? s.quantity : 'نفد'}
              </span>
            </div>
            {total > 0 && (
              <div className="h-1 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${barColor}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            )}
          </div>
        )
      })}
      <div className="text-xs text-gray-400 text-left pt-1 tabular-nums">
        الإجمالي: {total} وحدة
      </div>
    </div>
  )
}

// ── Chatter Entry ─────────────────────────────────────────────────────────────

function ActivityEntry({ activity, onDelete }) {
  const isSystem = activity.activity_type === 'status_changed'
  const isDispensed = activity.activity_type === 'item_dispensed'

  // System auto-logs rendered differently (like Odoo gray banners)
  if (isSystem || isDispensed) {
    return (
      <div className="flex items-start gap-3 py-2">
        <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0 text-sm">
          {activity.activity_icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="bg-gray-50 rounded-lg px-3 py-2 border border-gray-100">
            <p className="text-xs text-gray-600 leading-relaxed whitespace-pre-line">
              {activity.message}
            </p>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-gray-400">{activity.created_by_name}</span>
            <span className="text-gray-300 text-xs">·</span>
            <span className="text-xs text-gray-400" title={formatDateTime(activity.created_at)}>
              {timeAgo(activity.created_at)}
            </span>
          </div>
        </div>
      </div>
    )
  }

  // Human-posted activity (note, call, etc.)
  return (
    <div className="flex items-start gap-3 py-2">
      <InitialsAvatar name={activity.created_by_name} role={activity.created_by_role} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1 flex-wrap">
          <span className="text-sm font-semibold text-gray-800">{activity.created_by_name}</span>
          {activity.created_by_branch && (
            <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
              {activity.created_by_branch}
            </span>
          )}
          {!activity.is_deleted && (
            <span className="text-xs text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded border">
              {activity.activity_icon} {activity.activity_label}
            </span>
          )}
          <span
            className="text-xs text-gray-400 mr-auto"
            title={formatDateTime(activity.created_at)}
          >
            {timeAgo(activity.created_at)}
          </span>
          {/* Delete button — only for author / admin */}
          {activity.can_delete && onDelete && (
            <button
              onClick={() => onDelete(activity.id)}
              className="text-gray-300 hover:text-red-400 transition-colors p-0.5 rounded"
              title="حذف الرسالة"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          )}
        </div>

        {/* Tombstone — deleted message */}
        {activity.is_deleted ? (
          <div className="flex items-center gap-1.5 text-xs text-gray-400 italic bg-gray-50 border border-dashed border-gray-200 rounded-lg px-3 py-2">
            <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            <span>
              تم حذف هذه الرسالة
              {activity.deleted_by_name && ` بواسطة ${activity.deleted_by_name}`}
              {activity.deleted_at && ` · ${timeAgo(activity.deleted_at)}`}
            </span>
          </div>
        ) : (
          <>
            {/* Message bubble */}
            {activity.message && (
              <div className="bg-white border border-gray-200 rounded-xl rounded-tr-sm px-4 py-3 shadow-sm">
                <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
                  {activity.message}
                </p>
              </div>
            )}

            {/* Attachment */}
            {activity.attachment_url && (
              <div className="mt-2">
                <img
                  src={activity.attachment_url}
                  alt="مرفق"
                  className="rounded-lg max-h-48 border border-gray-200 object-contain cursor-pointer hover:opacity-90"
                  onClick={() => window.open(activity.attachment_url, '_blank')}
                />
              </div>
            )}

            {/* Voice note */}
            {activity.voice_note_url && (
              <div className="mt-2">
                <div className="flex items-center gap-1.5 text-xs text-gray-400 mb-1">
                  <span>🎙️</span>
                  <span>ملاحظة صوتية</span>
                </div>
                <audio
                  src={activity.voice_note_url}
                  controls
                  className="w-full h-8 max-w-sm"
                  style={{ direction: 'ltr' }}
                />
              </div>
            )}

            {/* Mentions */}
            {activity.mentioned_users_names?.length > 0 && (
              <div className="flex gap-1 mt-1 flex-wrap">
                {activity.mentioned_users_names.map(u => (
                  <span key={u.id} className="text-xs text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">
                    @{u.name}
                  </span>
                ))}
              </div>
            )}

            {/* Transfer reference */}
            {activity.transfer_request_id_ref && (
              <div className="mt-1 text-xs text-blue-600">
                🔀 طلب تحويل #{activity.transfer_request_id_ref}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Chatter Input ─────────────────────────────────────────────────────────────

function ChatterInput({ reservationId, onPosted }) {
  const [type, setType] = useState('note')
  const [message, setMessage] = useState('')
  const [file, setFile] = useState(null)
  const [voiceFile, setVoiceFile] = useState(null)
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef()
  const textRef = useRef()

  const handlePost = async () => {
    if (!message.trim() && !file && !voiceFile) {
      setError('اكتب رسالة أو أرفق صورة أو سجّل ملاحظة صوتية')
      return
    }
    setPosting(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('activity_type', type)
      fd.append('message', message)
      if (file) fd.append('attachment', file)
      if (voiceFile) fd.append('voice_note', voiceFile)
      await reservationsApi.logActivity(reservationId, fd)
      setMessage('')
      setFile(null)
      setVoiceFile(null)
      onPosted()
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setPosting(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      handlePost()
    }
  }

  return (
    <div className="border-t border-gray-100 pt-4 mt-2">
      {/* Type selector */}
      <div className="flex gap-1 mb-3 flex-wrap">
        {ACTIVITY_TYPE_OPTIONS.map(opt => (
          <button
            key={opt.value}
            onClick={() => setType(opt.value)}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              type === opt.value
                ? 'bg-brand-600 text-white border-brand-600'
                : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Text area */}
      <textarea
        ref={textRef}
        rows={3}
        value={message}
        onChange={e => setMessage(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="اكتب ملاحظة، نتيجة مكالمة، أو تحديثاً... (Ctrl+Enter للإرسال)"
        className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:border-brand-400 focus:ring-1 focus:ring-brand-200 placeholder-gray-400"
      />

      {/* Voice recorder */}
      <div className="mt-2">
        <VoiceNoteRecorder
          onRecorded={(audioFile) => setVoiceFile(audioFile)}
          onClear={() => setVoiceFile(null)}
          disabled={posting}
        />
      </div>

      {/* Footer row */}
      <div className="flex items-center gap-2 mt-2">
        {/* File attach */}
        <input type="file" accept="image/*" ref={fileRef} className="hidden"
          onChange={e => setFile(e.target.files[0])} />
        <button
          onClick={() => fileRef.current?.click()}
          className="text-gray-400 hover:text-brand-600 transition-colors p-1 rounded"
          title="إرفاق صورة"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>

        {file && (
          <span className="text-xs text-brand-600 bg-brand-50 px-2 py-0.5 rounded truncate max-w-32">
            📎 {file.name}
            <button onClick={() => setFile(null)} className="mr-1 text-gray-400 hover:text-red-500">✕</button>
          </span>
        )}

        {error && <span className="text-xs text-red-500 flex-1">{error}</span>}

        <div className="flex-1" />

        <span className="text-xs text-gray-300">Ctrl+Enter</span>
        <button
          onClick={handlePost}
          disabled={posting}
          className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-semibold px-4 py-1.5 rounded-lg transition-colors"
        >
          {posting ? 'جارٍ...' : 'إرسال'}
        </button>
      </div>
    </div>
  )
}

// ── Status Change Modal ───────────────────────────────────────────────────────

function ChangeStatusModal({ reservation, onClose, onSuccess }) {
  const qc = useQueryClient()
  const [newStatus, setNewStatus] = useState('')
  const [note, setNote] = useState('')

  const allowed = NEXT_STATUSES[reservation.status] || []
  const allowedOptions = STATUS_OPTIONS.filter(o => allowed.includes(o.value))

  const mutation = useMutation({
    mutationFn: () => reservationsApi.changeStatus(reservation.id, newStatus, note),
    onSuccess: () => {
      qc.invalidateQueries(['reservation', String(reservation.id)])
      qc.invalidateQueries(['reservations-kanban'])
      onSuccess?.()
      onClose()
    },
  })

  if (allowed.length === 0) return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="card max-w-sm w-full mx-4" onClick={e => e.stopPropagation()}>
        <p className="text-gray-500 text-center py-4 text-sm">لا يمكن تغيير حالة هذا الحجز</p>
        <button onClick={onClose} className="btn-secondary w-full">إغلاق</button>
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full mx-4 p-6" onClick={e => e.stopPropagation()} dir="rtl">
        <h3 className="font-bold text-gray-800 mb-4 text-base">تغيير حالة الحجز</h3>
        <div className="mb-3">
          <label className="label">الحالة الجديدة *</label>
          <div className="flex flex-col gap-2">
            {allowedOptions.map(o => {
              const sc = STATUS_COLOR_MAP[o.value] || {}
              return (
                <label key={o.value} className={`flex items-center gap-3 p-3 rounded-xl border-2 cursor-pointer transition-all ${
                  newStatus === o.value ? 'border-brand-400 bg-brand-50' : 'border-gray-200 hover:border-gray-300'
                }`}>
                  <input type="radio" name="status" value={o.value}
                    checked={newStatus === o.value}
                    onChange={() => setNewStatus(o.value)}
                    className="sr-only" />
                  <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0`}
                    style={{ background: sc.dot || '#9ca3af' }} />
                  <span className="text-sm font-medium text-gray-700">{o.label}</span>
                </label>
              )
            })}
          </div>
        </div>
        <div className="mb-4">
          <label className="label">ملاحظة (اختياري)</label>
          <textarea rows={2} className="input-field" value={note}
            onChange={e => setNote(e.target.value)} placeholder="سبب التغيير..." />
        </div>
        {mutation.isError && (
          <div className="text-red-600 text-xs mb-3 bg-red-50 rounded-lg px-3 py-2">
            {mutation.error?.response?.data?.detail || 'حدث خطأ'}
          </div>
        )}
        <div className="flex gap-2">
          <button onClick={onClose} className="btn-secondary flex-1">إلغاء</button>
          <button
            disabled={!newStatus || mutation.isPending}
            onClick={() => mutation.mutate()}
            className="btn-primary flex-1 disabled:opacity-50"
          >
            {mutation.isPending ? 'جارٍ...' : 'تأكيد'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── ERP Match Panel (post-fulfillment, doccode 115 مبيعات نقدية) ──────────────

const SOFTECH_DOCTYPE = {
  '11':  'موظفين',
  '15':  'تأمين صحي',
  '30':  'حجز',
  '110': 'مبيعات نقدية',
  '115': 'مبيعات لعميل',
  '120': 'مشتريات',
  '125': 'صرف تبادل بين الفروع',
  '126': 'استلام تبادل بين الفروع',
  '130': 'تحويل مخزن داخلي',
  '200': 'صرف مخزن',
  '501': 'جرد إضافة',
  '502': 'جرد خصم',
  '600': 'تسوية مخزون',
}

const RES_ERP_CFG = {
  pending:   { icon: '🔄', label: 'لم يُفحص', bg: '#f9fafb', text: '#6b7280', border: '#e5e7eb' },
  matched:   { icon: '✅', label: 'متطابق',   bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  partial:   { icon: '⚠️', label: 'جزئي',     bg: '#fffbeb', text: '#b45309', border: '#fcd34d' },
  not_found: { icon: '❌', label: 'غير موجود', bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
}

function ReservationERPMatchPanel({ r, onRefresh }) {
  const [checking, setChecking]  = useState(false)
  const [cooldown, setCooldown]  = useState(0)
  const cooldownRef              = useRef(null)
  const matchStatus = r.erp_match_status

  useEffect(() => () => { if (cooldownRef.current) clearInterval(cooldownRef.current) }, [])

  // Only show for fulfilled reservations where either:
  // - there is already a match status, OR
  // - admin can trigger the check
  if (r.status !== 'fulfilled') return null
  if (!matchStatus && !r.can_check_erp_match) return null

  const cfg          = RES_ERP_CFG[matchStatus] || RES_ERP_CFG.pending
  const matchedItems = r.erp_matched_items  || []
  const receiptLines = r.erp_receipt_lines  || []
  const customer     = r.erp_customer_info  || null
  const hasDocs      = matchStatus && matchStatus !== 'not_found'

  function startCooldown(seconds = 60) {
    setCooldown(seconds)
    if (cooldownRef.current) clearInterval(cooldownRef.current)
    cooldownRef.current = setInterval(() => {
      setCooldown(prev => {
        if (prev <= 1) { clearInterval(cooldownRef.current); cooldownRef.current = null; return 0 }
        return prev - 1
      })
    }, 1000)
  }

  async function runCheck() {
    setChecking(true)
    try {
      await reservationsApi.checkErpMatch(r.id)
      onRefresh()
      startCooldown(60)
    } catch (e) {
      const msg = e.response?.data?.detail || 'حدث خطأ أثناء التحقق'
      if (e.response?.status === 429) {
        const match = msg.match(/(\d+)/)
        startCooldown(match ? parseInt(match[1], 10) : 20)
      }
      alert(msg)
    } finally { setChecking(false) }
  }

  return (
    <div className="card border-2 animate-fade-in" style={{ borderColor: cfg.border }}>

      {/* ── Header row ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 mb-4">
        <div className="text-xl">{cfg.icon}</div>
        <div className="flex-1">
          <div className="font-bold text-sm text-gray-800">مطابقة مستند ERP — مبيعات لعميل</div>
          {r.erp_reference ? (
            <div className="text-xs text-gray-400 mt-0.5">
              رقم المستند:{' '}
              <span className="font-mono text-purple-700 bg-purple-50 px-1.5 py-0.5 rounded text-xs">
                {r.erp_reference}
              </span>
            </div>
          ) : (
            <div className="text-xs text-amber-600 mt-0.5">
              🔎 لم يُدخَل رقم المستند — سيتم البحث تلقائياً عبر الأصناف والتاريخ
            </div>
          )}
        </div>
        {matchStatus && (
          <span className="px-2.5 py-1 rounded-full text-xs font-bold"
            style={{ background: cfg.bg, color: cfg.text, border: `1px solid ${cfg.border}` }}>
            {cfg.label}
          </span>
        )}
      </div>

      {/* ── Detail message ──────────────────────────────────────────────────── */}
      {r.erp_match_detail && (
        <div className="text-sm text-gray-700 bg-gray-50 rounded-xl px-3 py-2.5 mb-4 leading-relaxed">
          {r.erp_match_detail}
        </div>
      )}

      {hasDocs && (
        <>
          {/* ── Document info cards ─────────────────────────────────────────── */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">

            {r.erp_match_doc_code && (
              <div className="bg-white rounded-xl border border-gray-100 px-3 py-2 text-center">
                <div className="text-xs text-gray-400">نوع المستند</div>
                <div className="text-sm font-semibold text-gray-800">
                  {SOFTECH_DOCTYPE[r.erp_match_doc_code] || r.erp_match_doc_code}
                </div>
                <div className="text-[10px] font-mono text-gray-400 mt-0.5">كود: {r.erp_match_doc_code}</div>
              </div>
            )}

            {r.erp_match_doc_date && (
              <div className="bg-white rounded-xl border border-gray-100 px-3 py-2 text-center">
                <div className="text-xs text-gray-400">تاريخ المستند</div>
                <div className="text-sm font-semibold text-gray-800" dir="ltr">
                  {new Date(r.erp_match_doc_date).toLocaleDateString('en-GB')}
                </div>
              </div>
            )}

            {r.erp_match_doc_value != null && (
              <div className="bg-white rounded-xl border border-gray-100 px-3 py-2 text-center">
                <div className="text-xs text-gray-400">قيمة المستند</div>
                <div className="text-sm font-semibold text-gray-800">
                  {parseFloat(r.erp_match_doc_value).toLocaleString('en-US')} ج.م
                </div>
              </div>
            )}

            {r.erp_match_trans_time && (
              <div className="bg-white rounded-xl border border-gray-100 px-3 py-2 text-center">
                <div className="text-xs text-gray-400">وقت المعاملة</div>
                <div className="text-sm font-semibold text-gray-800" dir="ltr">
                  {new Date(r.erp_match_trans_time).toLocaleTimeString('en-GB', { hour12: false })}
                </div>
                <div className="text-[10px] text-gray-400" dir="ltr">
                  {new Date(r.erp_match_trans_time).toLocaleDateString('en-GB')}
                </div>
              </div>
            )}

            {(r.erp_match_user_id || r.erp_match_user_code) && (
              <div className="bg-white rounded-xl border border-gray-100 px-3 py-2 text-center">
                <div className="text-xs text-gray-400">المستخدم (ERP)</div>
                {r.erp_match_user_id && (
                  <div className="text-sm font-bold text-purple-700">{r.erp_match_user_id}</div>
                )}
                {r.erp_match_user_name && (
                  <div className="text-[11px] text-gray-500">{r.erp_match_user_name}</div>
                )}
                {r.erp_match_user_code && (
                  <div className="text-[10px] font-mono text-gray-400">كود: {r.erp_match_user_code}</div>
                )}
              </div>
            )}

            {r.erp_match_store_code && (
              <div className="bg-white rounded-xl border border-gray-100 px-3 py-2 text-center">
                <div className="text-xs text-gray-400">المخزن</div>
                <div className="text-sm font-mono font-semibold text-gray-800">{r.erp_match_store_code}</div>
              </div>
            )}
          </div>

          {/* ── Customer card (from SOFTECH localcustomers) ─────────────────── */}
          {customer && (customer.phcode || customer.name || customer.phone) && (
            <div className="bg-indigo-50 border border-indigo-100 rounded-xl px-4 py-3 mb-4">
              <div className="text-xs font-semibold text-indigo-500 uppercase tracking-wide mb-2">
                👤 بيانات العميل (SOFTECH)
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {customer.phcode && (
                  <span className="font-mono text-xs font-bold bg-indigo-100 text-indigo-700 px-2.5 py-1 rounded-lg">
                    PIC: {customer.phcode}
                  </span>
                )}
                {customer.name && (
                  <span className="text-sm font-semibold text-gray-800">{customer.name}</span>
                )}
                {customer.phone && (
                  <span className="text-sm font-mono text-brand-600 bg-white border border-gray-200 px-2.5 py-0.5 rounded-lg" dir="ltr">
                    {customer.phone}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* ── Reservation item match (single-item status) ──────────────────── */}
          {matchedItems.length > 0 && (
            <div className="mb-4">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                تطابق الصنف المحجوز
              </div>
              <div className="divide-y divide-gray-100 rounded-xl border border-gray-100 overflow-hidden">
                {matchedItems.map((m, i) => {
                  const lvlCfg = m.match_level === 'full'
                    ? { icon: '✅', text: 'text-green-700', bg: 'bg-green-50' }
                    : m.match_level === 'partial'
                    ? { icon: '⚠️', text: 'text-amber-700', bg: 'bg-amber-50' }
                    : { icon: '❌', text: 'text-red-600', bg: 'bg-red-50' }
                  return (
                    <div key={i} className={`flex items-center gap-3 px-3 py-2.5 ${lvlCfg.bg}`}>
                      <span className="text-sm">{lvlCfg.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-gray-800 break-words">{m.itemname}</div>
                        <div className="text-[10px] font-mono text-gray-400">{m.itemcode}</div>
                      </div>
                      <div className="text-xs text-right whitespace-nowrap">
                        <span className="text-gray-500">طُلب: </span>
                        <span className="font-mono font-semibold">{m.requested_qty}</span>
                        {m.erp_qty != null && (
                          <>
                            <span className="text-gray-400 mx-1">|</span>
                            <span className="text-gray-500">ERP: </span>
                            <span className={`font-mono font-semibold ${lvlCfg.text}`}>{m.erp_qty}</span>
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ── Full receipt lines (all items on the document) ───────────────── */}
          {receiptLines.length > 0 && (
            <div className="mb-4">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                📋 محتوى الإيصال الكامل ({receiptLines.length} صنف)
              </div>
              <div className="rounded-xl border border-gray-200 overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <th className="text-right px-3 py-2 font-semibold text-gray-500">الصنف</th>
                      <th className="text-center px-2 py-2 font-semibold text-gray-500 whitespace-nowrap">الكمية</th>
                      <th className="text-center px-2 py-2 font-semibold text-gray-500 whitespace-nowrap">الإجمالي</th>
                      <th className="text-center px-2 py-2 font-semibold text-gray-500">المخزن</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {receiptLines.map((line, i) => {
                      // Highlight the reservation's item
                      const isReservationItem = matchedItems.some(m => m.itemcode === line.itemcode)
                      return (
                        <tr key={i} className={isReservationItem ? 'bg-purple-50' : 'bg-white hover:bg-gray-50'}>
                          <td className="px-3 py-2">
                            <div className="font-medium text-gray-800 break-words max-w-[180px]" title={line.itemname}>
                              {line.itemname || <span className="text-gray-400 italic">غير محدد</span>}
                              {isReservationItem && (
                                <span className="mr-1.5 text-[9px] bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded font-bold">محجوز</span>
                              )}
                            </div>
                            <div className="font-mono text-gray-400 text-[10px]">{line.itemcode}</div>
                          </td>
                          <td className="px-2 py-2 text-center font-mono font-semibold text-gray-700 tabular-nums">
                            {line.qty}
                          </td>
                          <td className="px-2 py-2 text-center font-mono text-gray-600 tabular-nums whitespace-nowrap">
                            {line.price > 0
                              ? `${Number(line.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م`
                              : '—'}
                          </td>
                          <td className="px-2 py-2 text-center font-mono text-gray-500">
                            {line.storecode || '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Footer: meta + check button ────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-[11px] text-gray-400 space-y-0.5">
          {r.erp_check_attempts > 0 && (
            <div>عدد المحاولات: {r.erp_check_attempts}</div>
          )}
          {r.erp_last_checked && (
            <div dir="ltr">
              آخر فحص: {new Date(r.erp_last_checked).toLocaleString('en-GB', { hour12: false })}
            </div>
          )}
        </div>

        {r.can_check_erp_match && (
          <div className="flex flex-col items-end gap-1">
            <button
              onClick={runCheck}
              disabled={checking || cooldown > 0}
              title={cooldown > 0 ? `يمكن إعادة الفحص بعد ${cooldown} ثانية` : ''}
              className="text-xs px-3 py-1.5 rounded-lg font-semibold bg-purple-600 hover:bg-purple-700 text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {checking ? (
                <>
                  <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  جارٍ الفحص...
                </>
              ) : cooldown > 0 ? `⏳ ${cooldown}ث`
                : matchStatus ? (r.erp_reference ? '🔍 إعادة الفحص' : '🔎 إعادة البحث')
                : (r.erp_reference ? '🔍 فحص الآن' : '🔎 بحث تلقائي')}
            </button>
            {cooldown > 0 && (
              <span className="text-[10px] text-gray-400">إعادة الفحص متاحة بعد {cooldown}ث</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Reservation Lines Panel ────────────────────────────────────────────────────

// ── Per-item stock row (fetches its own stock) ────────────────────────────────
function ItemStockRow({ itemId }) {
  const { data: stocks = [], isFetching } = useQuery({
    queryKey: ['item-stock-detail', itemId],
    queryFn: () => import('../api/client').then(m => m.default).then(api =>
      api.get(`/items/${itemId}/stock/`).then(r => r.data)
    ),
    enabled: !!itemId,
    staleTime: 60_000,
  })
  if (isFetching) return <div className="text-[10px] text-gray-300 mt-1.5 animate-pulse">جارٍ تحميل المخزون...</div>
  if (!stocks.length) return <div className="text-[10px] text-gray-300 mt-1.5">لا توجد بيانات مخزون</div>
  // endpoint returns quantity_on_hand (not quantity) and branch_name_ar
  const inStock = stocks.filter(s => (parseFloat(s.quantity_on_hand) || 0) > 0)
  return (
    <div className="mt-2 space-y-1">
      {inStock.slice(0, 5).map(s => {
        const qty = parseFloat(s.quantity_on_hand) || 0
        const pct = Math.min(100, (qty / 20) * 100)
        const color = qty >= 5 ? 'bg-emerald-400' : qty > 0 ? 'bg-amber-400' : 'bg-red-300'
        const branchName = s.branch_name_ar || s.branch_name || '—'
        return (
          <div key={s.branch} className="flex items-center gap-2">
            <div className="text-[10px] text-gray-500 w-28 truncate shrink-0">{branchName}</div>
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
            </div>
            <div className="text-[10px] font-mono font-bold text-gray-600 w-12 text-left shrink-0">{qty.toLocaleString()}</div>
          </div>
        )
      })}
      {inStock.length === 0 && <div className="text-[10px] text-red-400">غير متوفر في أي فرع</div>}
    </div>
  )
}

// ── Unified all-items panel (primary + extra lines) ───────────────────────────
function AllItemsPanel({ r, onRefresh }) {
  const [adding, setAdding] = useState(false)
  const [newItem, setNewItem] = useState({ selectedItem: null, manual_item_name: '', quantity_requested: 1 })
  const [saving, setSaving] = useState(false)

  const allItems = getAllReservationItems(r)
  const hasPrimary = !!(r.item_name || r.manual_item_name)
  const lines = r.lines || []
  const isLocked = r.status !== 'pending'

  return (
    <div className="card">
      <h3 className="font-bold text-gray-800 text-sm mb-3 flex items-center gap-2">
        <span>📦</span> أصناف الحجز
        <span className="text-xs font-normal text-gray-400">({allItems.length} صنف)</span>
      </h3>

      <div className="space-y-3">
        {/* Primary item */}
        {hasPrimary && (
          <div className="rounded-xl border border-indigo-100 bg-indigo-50/40 p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold text-gray-900 leading-tight">{r.item_name || r.manual_item_name}</div>
                {r.item_scientific && <div className="text-[10px] italic text-gray-400 mt-0.5">{r.item_scientific}</div>}
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  {r.item_softech_id && <span className="text-[10px] font-mono text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">كود: {r.item_softech_id}</span>}
                  {r.item_sale_price != null && (
                    <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded">
                      💰 {Number(r.item_sale_price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م
                    </span>
                  )}
                </div>
              </div>
              <div className="shrink-0 text-sm font-bold text-gray-700 bg-white border border-gray-200 rounded-lg px-2 py-1 tabular-nums">
                × {r.quantity_requested}
              </div>
            </div>
            {r.item && <ItemStockRow itemId={r.item} />}
          </div>
        )}

        {/* Extra lines */}
        {lines.map(line => (
          <div key={line.id} className="rounded-xl border border-gray-100 bg-white p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-gray-800 leading-tight">{line.item_name}</div>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  {line.item_softech_id && <span className="text-[10px] font-mono text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded">كود: {line.item_softech_id}</span>}
                  {line.item_sale_price != null && (
                    <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded">
                      💰 {Number(line.item_sale_price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م
                    </span>
                  )}
                  {line.notes && <span className="text-[10px] text-gray-400">{line.notes}</span>}
                </div>
              </div>
              <div className="shrink-0 flex items-center gap-1">
                <div className="text-sm font-bold text-gray-700 bg-white border border-gray-200 rounded-lg px-2 py-1 tabular-nums">× {line.quantity_requested}</div>
                {!isLocked && (
                  <button
                    onClick={async () => {
                      if (!window.confirm('حذف هذا الصنف؟')) return
                      await import('../api/client').then(m => m.reservationsApi).then(api => api.deleteLine(r.id, line.id))
                      onRefresh()
                    }}
                    className="text-gray-300 hover:text-red-400 text-xs px-1 py-1"
                    title="حذف"
                  >✕</button>
                )}
              </div>
            </div>
            {line.item && <ItemStockRow itemId={line.item} />}
          </div>
        ))}
      </div>

      {/* Add line — hidden once reservation leaves pending */}
      {isLocked ? (
        <div className="mt-3 flex items-center gap-1.5 text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <span>🔒</span>
          <span>الحجز مغلق للتعديل — الأصناف لا تُعدَّل بعد مرحلة قيد الانتظار</span>
        </div>
      ) : (
        <>
          <button onClick={() => setAdding(a => !a)} className="mt-3 text-xs text-brand-600 hover:text-brand-700 font-medium">
            {adding ? '▲ إغلاق' : '+ إضافة صنف'}
          </button>
          {adding && (
            <div className="mt-2 space-y-2">
              <ItemSearchWidget
                selected={newItem.selectedItem}
                onSelect={item => setNewItem(n => ({ ...n, selectedItem: item, manual_item_name: '' }))}
                onClear={() => setNewItem(n => ({ ...n, selectedItem: null }))}
                placeholder="ابحث عن صنف بالاسم أو الكود..."
                showStockBadge={true}
              />
              {newItem.selectedItem && (
                <div className="flex items-center gap-2 bg-indigo-50 border border-indigo-200 rounded-xl px-3 py-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold text-gray-800 break-words">{newItem.selectedItem.name}</div>
                    {newItem.selectedItem.softech_id && (
                      <div className="text-[10px] font-mono text-indigo-500">كود: {newItem.selectedItem.softech_id}</div>
                    )}
                  </div>
                  <button onClick={() => setNewItem(n => ({ ...n, selectedItem: null }))} className="text-gray-400 hover:text-red-400 text-xs">✕</button>
                </div>
              )}
              <div className="flex items-center gap-2">
                <label className="text-xs text-gray-500 shrink-0">الكمية:</label>
                <input
                  type="number" min="1"
                  className="input-field w-20 text-xs"
                  value={newItem.quantity_requested}
                  onChange={e => setNewItem(n => ({ ...n, quantity_requested: Number(e.target.value) }))}
                />
                <button
                  disabled={saving || (!newItem.selectedItem && !newItem.manual_item_name.trim())}
                  className="btn-primary text-xs py-1.5 px-4 disabled:opacity-40"
                  onClick={async () => {
                    setSaving(true)
                    try {
                      const api = await import('../api/client').then(m => m.reservationsApi)
                      const payload = newItem.selectedItem
                        ? { item: newItem.selectedItem.id, quantity_requested: newItem.quantity_requested }
                        : { manual_item_name: newItem.manual_item_name, quantity_requested: newItem.quantity_requested }
                      await api.addLine(r.id, payload)
                      setNewItem({ selectedItem: null, manual_item_name: '', quantity_requested: 1 })
                      setAdding(false)
                      onRefresh()
                    } finally { setSaving(false) }
                  }}
                >{saving ? '...' : 'إضافة'}</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ReservationLinesPanel({ reservationId, lines, onRefresh }) {
  const [adding, setAdding] = useState(false)
  const [newItem, setNewItem] = useState({ item: '', item_name: '', manual_item_name: '', quantity_requested: 1, notes: '' })
  const [saving, setSaving] = useState(false)

  if (!lines || lines.length === 0) return null

  return (
    <div className="card">
      <h3 className="font-bold text-gray-800 text-sm mb-3 flex items-center gap-2">
        <span>📦</span> أصناف الحجز
        <span className="text-xs font-normal text-gray-400">({lines.length} صنف)</span>
      </h3>
      <div className="divide-y divide-gray-100 rounded-xl border border-gray-100 overflow-hidden">
        {lines.map(line => (
          <div key={line.id} className="flex items-center gap-3 px-3 py-2.5 bg-white hover:bg-gray-50">
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-gray-800 break-words">{line.item_name}</div>
              {line.item_softech_id && (
                <div className="text-[10px] font-mono text-gray-400">{line.item_softech_id}</div>
              )}
              {line.notes && (
                <div className="text-xs text-gray-400 mt-0.5">{line.notes}</div>
              )}
            </div>
            <div className="text-sm font-bold text-gray-700 tabular-nums whitespace-nowrap">
              × {line.quantity_requested}
            </div>
            {line.item_sale_price && (
              <div className="text-xs text-gray-400 tabular-nums whitespace-nowrap">
                {line.item_sale_price} ج.م
              </div>
            )}
            <button
              onClick={async () => {
                if (!window.confirm('حذف هذا الصنف؟')) return
                await reservationsApi.deleteLine(reservationId, line.id)
                onRefresh()
              }}
              className="text-gray-300 hover:text-red-400 text-xs px-1"
              title="حذف"
            >✕</button>
          </div>
        ))}
      </div>

      {/* Add line */}
      <button
        onClick={() => setAdding(a => !a)}
        className="mt-3 text-xs text-brand-600 hover:text-brand-700 font-medium"
      >
        {adding ? '▲ إغلاق' : '+ إضافة صنف'}
      </button>
      {adding && (
        <div className="mt-2 flex gap-2 flex-wrap">
          <input
            className="input-field flex-1 text-xs"
            placeholder="اسم الصنف يدوياً..."
            value={newItem.manual_item_name}
            onChange={e => setNewItem(n => ({ ...n, manual_item_name: e.target.value }))}
          />
          <input
            type="number"
            min="1"
            className="input-field w-16 text-xs"
            placeholder="الكمية"
            value={newItem.quantity_requested}
            onChange={e => setNewItem(n => ({ ...n, quantity_requested: Number(e.target.value) }))}
          />
          <button
            disabled={saving || !newItem.manual_item_name.trim()}
            className="btn-primary text-xs py-1 px-3 disabled:opacity-40"
            onClick={async () => {
              setSaving(true)
              try {
                await reservationsApi.addLine(reservationId, {
                  manual_item_name: newItem.manual_item_name,
                  quantity_requested: newItem.quantity_requested,
                })
                setNewItem({ item: '', item_name: '', manual_item_name: '', quantity_requested: 1, notes: '' })
                setAdding(false)
                onRefresh()
              } finally { setSaving(false) }
            }}
          >{saving ? '...' : 'إضافة'}</button>
        </div>
      )}
    </div>
  )
}

// ── Customer History Panel ─────────────────────────────────────────────────────

const STATUS_COLOR_BADGE = {
  pending:   'bg-gray-100 text-gray-600',
  available: 'bg-orange-100 text-orange-700',
  contacted: 'bg-blue-100 text-blue-700',
  confirmed: 'bg-indigo-100 text-indigo-700',
  fulfilled: 'bg-green-100 text-green-700',
  cancelled: 'bg-red-100 text-red-600',
  expired:   'bg-red-100 text-red-600',
}

function CustomerHistoryPanel({ reservationId, customerId }) {
  const { data: history = [], isLoading } = useQuery({
    queryKey: ['reservation-customer-history', reservationId],
    queryFn:  () => reservationsApi.customerHistory(reservationId).then(r => r.data),
    enabled:  !!customerId,
    staleTime: 60_000,
  })

  if (!customerId) return null
  if (isLoading) return (
    <div className="card">
      <h3 className="font-bold text-gray-800 text-sm mb-2">سجل طلبات العميل</h3>
      <div className="text-xs text-gray-400 py-3 text-center animate-pulse">جارٍ التحميل...</div>
    </div>
  )
  if (history.length === 0) return (
    <div className="card">
      <h3 className="font-bold text-gray-800 text-sm mb-2">سجل طلبات العميل</h3>
      <div className="text-xs text-gray-400 py-3 text-center">لا يوجد حجوزات سابقة</div>
    </div>
  )

  return (
    <div className="card">
      <h3 className="font-bold text-gray-800 text-sm mb-3 flex items-center gap-2">
        <span>🕐</span> سجل طلبات العميل
        <span className="text-xs font-normal text-gray-400">(آخر {history.length})</span>
      </h3>
      <div className="space-y-2">
        {history.map(h => (
          <a
            key={h.id}
            href={`/reservations/${h.id}`}
            className="flex items-start gap-2 p-2 rounded-lg hover:bg-gray-50 transition-colors border border-gray-100"
          >
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-gray-700 break-words">{h.item_name}</div>
              <div className="text-[10px] text-gray-400">{h.branch_name} · #{h.id}</div>
            </div>
            <div className="flex flex-col items-end gap-1 flex-shrink-0">
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${STATUS_COLOR_BADGE[h.status] || 'bg-gray-100 text-gray-500'}`}>
                {h.status_label}
              </span>
              <span className="text-[10px] text-gray-300">
                {h.created_at ? toLatinDigits(format(new Date(h.created_at), 'd MMM yy', { locale: ar })) : ''}
              </span>
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReservationDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [showStatusModal, setShowStatusModal] = useState(false)
  const [showPrintModal, setShowPrintModal] = useState(false)
  const [imageUploading, setImageUploading] = useState(false)
  const imageInputRef = useRef()
  const chatEndRef = useRef()

  const { data: r, isLoading, isError } = useQuery({
    queryKey: ['reservation', id],
    queryFn: () => reservationsApi.get(id).then(res => res.data),
    refetchInterval: 60_000,
  })

  const { data: extraImages = [], refetch: refetchImages } = useQuery({
    queryKey: ['reservation-images', id],
    queryFn: () => reservationsApi.getImages(id).then(res => res.data),
    enabled: !!id,
  })

  // Pharmacy profile — for customer-facing receipt and WhatsApp message
  const { data: pharmacy = null } = useQuery({
    queryKey: ['pharmacy-profile'],
    queryFn:  () => configApi.pharmacyProfile().then(res => res.data),
    staleTime: 5 * 60_000,   // cache for 5 min
  })

  // Scroll chatter to bottom on load
  useEffect(() => {
    if (r?.activities?.length) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [r?.activities?.length])

  const invalidate = () => {
    qc.invalidateQueries(['reservation', id])
    qc.invalidateQueries(['reservations-kanban'])
  }

  const handleDeleteActivity = async (activityId) => {
    if (!window.confirm('هل تريد حذف هذه الرسالة؟ ستبقى علامة الحذف مرئية للجميع.')) return
    try {
      await reservationsApi.deleteActivity(r.id, activityId)
      invalidate()
    } catch (e) {
      alert(e.response?.data?.detail || 'تعذّر حذف الرسالة')
    }
  }

  const handleUploadImages = async (e) => {
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setImageUploading(true)
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('images', f))
      await reservationsApi.uploadImages(id, fd)
      refetchImages()
    } catch { /* silent */ } finally {
      setImageUploading(false)
      if (imageInputRef.current) imageInputRef.current.value = ''
    }
  }

  const handleDeleteImage = async (imageId) => {
    if (!window.confirm('حذف هذه الصورة؟')) return
    try {
      await reservationsApi.deleteImage(id, imageId)
      refetchImages()
    } catch { /* silent */ }
  }

  if (isLoading) return (
    <div className="p-8 flex flex-col gap-4 animate-pulse" dir="rtl">
      <div className="h-8 w-48 bg-gray-200 rounded-xl" />
      <div className="grid md:grid-cols-3 gap-5">
        <div className="md:col-span-2 space-y-4">
          {[1,2,3].map(i => <div key={i} className="h-32 bg-gray-100 rounded-xl" />)}
        </div>
        <div className="h-96 bg-gray-100 rounded-xl" />
      </div>
    </div>
  )

  if (isError || !r) return (
    <div className="p-8 text-center" dir="rtl">
      <div className="text-5xl mb-3">😕</div>
      <div className="text-gray-600">لم يتم العثور على الحجز</div>
      <button onClick={() => navigate('/reservations')} className="btn-secondary mt-4">
        ← العودة للحجوزات
      </button>
    </div>
  )

  const canChange = !['fulfilled', 'cancelled', 'expired'].includes(r.status)
  const userRole = user?.role || 'viewer'
  const roleActions = (ROLE_ACTIONS[userRole] || []).filter(a =>
    (NEXT_STATUSES[r.status] || []).includes(a.status)
  )

  const sc = STATUS_COLOR_MAP[r.status] || STATUS_COLOR_MAP.pending

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {showStatusModal && (
        <ChangeStatusModal
          reservation={r}
          onClose={() => setShowStatusModal(false)}
          onSuccess={invalidate}
        />
      )}
      {showPrintModal && (
        <PrintReceiptModal
          type="reservation"
          docId={r.id}
          onClose={() => setShowPrintModal(false)}
        />
      )}

      {/* ── Page header ───────────────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-4 flex-wrap">
          <button
            onClick={() => navigate('/reservations')}
            className="text-gray-400 hover:text-gray-700 transition-colors p-1 rounded-lg hover:bg-gray-100"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-black text-gray-900">حجز #{r.id}</h1>
              <span className={`badge ${sc.bg} ${sc.text}`}>{r.status_label}</span>
              <PriorityBadge priority={r.priority} />
              {r.item_softech_id && (
                <span className="text-xs font-mono text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
                  {r.item_softech_id}
                </span>
              )}
            </div>
            <div className="text-xs text-gray-400 mt-0.5 flex items-center gap-2">
              <span>{formatDateTime(r.created_at)}</span>
              {r.created_by_name && <><span>·</span><span>{r.created_by_name}</span></>}
              {r.branch_name && <><span>·</span><span>🏥 {r.branch_name}</span></>}
            </div>
          </div>

          {/* Role-based quick action buttons */}
          <div className="flex gap-2 flex-wrap items-center">

            {/* ── Internal-use tools ── clearly labelled for staff only */}
            <div className="flex items-center gap-1.5 border border-dashed border-gray-300 rounded-xl px-2.5 py-1.5 bg-gray-50">
              <span className="text-[10px] font-semibold text-gray-400 tracking-wide whitespace-nowrap">🔒 داخلي</span>
              <div className="w-px h-4 bg-gray-200" />
              <button
                onClick={() => setShowPrintModal(true)}
                className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-gray-300 text-gray-600 hover:bg-white transition-colors"
                title="طباعة الإيصال الداخلي"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
                </svg>
                طباعة
              </button>
              <WhatsAppShareButton type="reservation" docId={r.id} size="sm" />
            </div>

            {/* Reverse bridge: expired/cancelled → lost demand (manager-gated) */}
            {['expired', 'cancelled'].includes(r.status) && (
              <CanDo module="demand" action="approve">
                <button
                  onClick={async () => {
                    if (!window.confirm('تحويل هذا الحجز إلى طلب ضائع لتتبعه واسترداده لاحقاً عند توفر الصنف؟')) return
                    try {
                      const res = await demandApi.fromReservation({ reservation_id: r.id })
                      if (res?.data?.id) navigate(`/demand/${res.data.id}`)
                    } catch (e) {
                      alert(e.response?.data?.detail || 'تعذّر التحويل')
                    }
                  }}
                  className="text-sm px-3 py-1.5 rounded-lg font-medium border border-amber-300 text-amber-700 hover:bg-amber-50 transition-colors"
                  title="تحويل إلى طلب ضائع للتتبع والاسترداد"
                >
                  📥 تحويل لطلب ضائع
                </button>
              </CanDo>
            )}

            <CanDo module="reservations" action="edit">
              {roleActions.map(a => {
                const asc = STATUS_COLOR_MAP[a.status] || {}
                return (
                  <button
                    key={a.status}
                    onClick={() => {
                      reservationsApi.changeStatus(r.id, a.status, '').then(invalidate)
                    }}
                    className="text-sm px-3 py-1.5 rounded-lg font-medium border transition-colors hover:opacity-90"
                    style={{
                      borderColor: asc.dot || '#d1d5db',
                      color: asc.dot || '#6b7280',
                    }}
                  >
                    {a.label}
                  </button>
                )
              })}
            </CanDo>
            <CanDo module="reservations" action="approve">
              {canChange && (
                <button onClick={() => setShowStatusModal(true)} className="btn-primary text-sm">
                  تغيير الحالة
                </button>
              )}
            </CanDo>
          </div>
        </div>
      </div>

      {/* ── Body ──────────────────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-6 py-6 grid lg:grid-cols-3 gap-6">

        {/* ── Left / Main: Chatter ──────────────────────────────────────── */}
        <div className="lg:col-span-2 flex flex-col gap-5">

          {/* Chatter card */}
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-bold text-gray-800 text-sm">
                سجل الأنشطة
                {r.activities?.length > 0 && (
                  <span className="mr-2 text-xs font-normal text-gray-400">
                    ({r.activities.length} إدخال)
                  </span>
                )}
              </h3>
            </div>

            {/* Activities feed */}
            <div className="space-y-0 divide-y divide-gray-50 max-h-96 overflow-y-auto pr-1">
              {(!r.activities || r.activities.length === 0) && (
                <div className="text-center py-8">
                  <div className="text-3xl mb-2">💬</div>
                  <div className="text-sm text-gray-400">لا توجد أنشطة بعد</div>
                  <div className="text-xs text-gray-300 mt-1">سيظهر هنا كل تحديث وتواصل</div>
                </div>
              )}
              {r.activities?.map(activity => (
                <ActivityEntry key={activity.id} activity={activity} onDelete={handleDeleteActivity} />
              ))}
              <div ref={chatEndRef} />
            </div>

            {/* Compose box */}
            <ChatterInput
              reservationId={r.id}
              onPosted={invalidate}
            />
          </div>


          {/* ERP Match Panel — visible only after تم التسليم */}
          <ReservationERPMatchPanel r={r} onRefresh={invalidate} />

          {/* Notes */}
          {r.notes && (
            <div className="card">
              <h3 className="font-bold text-gray-700 mb-2 text-sm">ملاحظات الحجز</h3>
              <p className="text-gray-600 text-sm leading-relaxed">{r.notes}</p>
            </div>
          )}

          {/* Images gallery */}
          {(r.image_url || extraImages.length > 0) && (
            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-bold text-gray-700 text-sm">المرفقات</h3>
                <label className={`cursor-pointer text-xs px-2.5 py-1 rounded-lg border ${imageUploading ? 'opacity-50 pointer-events-none' : 'border-gray-300 hover:bg-gray-50'} text-gray-600 flex items-center gap-1`}>
                  <input ref={imageInputRef} type="file" accept="image/*" multiple className="hidden" onChange={handleUploadImages} />
                  {imageUploading ? '⏳ جارٍ الرفع...' : '+ إضافة صور'}
                </label>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {r.image_url && (
                  <img src={r.image_url} alt="مرفق" className="rounded-xl border border-gray-200 object-contain w-full max-h-48 cursor-pointer hover:opacity-90" onClick={() => window.open(r.image_url, '_blank')} />
                )}
                {extraImages.map(img => (
                  <div key={img.id} className="relative group">
                    <img src={img.image_url} alt="مرفق" className="rounded-xl border border-gray-200 object-contain w-full max-h-48 cursor-pointer hover:opacity-90" onClick={() => window.open(img.image_url, '_blank')} />
                    <button onClick={() => handleDeleteImage(img.id)} className="absolute top-1 left-1 bg-red-600 text-white rounded-full w-5 h-5 text-xs hidden group-hover:flex items-center justify-center">×</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Upload images when none attached yet */}
          {!r.image_url && extraImages.length === 0 && (
            <div className="card">
              <h3 className="font-bold text-gray-700 text-sm mb-3">المرفقات</h3>
              <label className={`cursor-pointer flex flex-col items-center gap-2 py-6 border-2 border-dashed border-gray-200 rounded-xl text-gray-400 text-sm hover:border-brand-400 hover:text-brand-600 transition-colors ${imageUploading ? 'opacity-50 pointer-events-none' : ''}`}>
                <input ref={imageInputRef} type="file" accept="image/*" multiple className="hidden" onChange={handleUploadImages} />
                <span className="text-2xl">🖼️</span>
                {imageUploading ? 'جارٍ الرفع...' : 'اضغط لرفع صور'}
              </label>
            </div>
          )}
        </div>

        {/* ── Right sidebar ─────────────────────────────────────────────── */}
        <div className="flex flex-col gap-4">

          {/* Customer */}
          <div className="card">
            <h3 className="font-bold mb-3 text-xs uppercase tracking-wide text-gray-400">العميل</h3>
            <div className="text-base font-bold text-gray-900">{r.contact_name}</div>
            <div className="text-brand-600 font-mono text-sm mt-0.5" dir="ltr">{r.contact_phone}</div>
            {r.customer_name !== r.contact_name && (
              <div className="text-xs text-gray-400 mt-1">في النظام: {r.customer_name}</div>
            )}
            {r.customer_softech_pic && (
              <div className="text-xs font-mono text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded mt-1.5 inline-block">
                PIC: {r.customer_softech_pic}
              </div>
            )}
            <button
              onClick={() => navigate(`/customers/${r.customer_id || r.customer}`)}
              className="text-brand-600 text-xs hover:underline mt-2 inline-flex items-center gap-1"
            >
              سجل العميل الكامل ←
            </button>

            {/* ── Customer-facing actions ───────────────────────────────────────
                Visually distinct from internal tools: emerald theme, customer context.
                Content: name, item, code, qty only — NO prices, NO internal data.      */}
            {r.contact_phone && (
              <div className="mt-4 pt-4 border-t-2 border-dashed border-emerald-200">
                <div className="flex items-center gap-1.5 mb-3">
                  <span className="text-xs font-bold text-emerald-700 tracking-wide">📱 إرسال للعميل</span>
                  <span className="text-[10px] text-emerald-500 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded-full">بدون أسعار</span>
                </div>

                {/* WhatsApp to customer's number */}
                <button
                  onClick={() => {
                    const phone = toWhatsAppPhone(r.contact_phone)
                    if (!phone) return
                    const text = encodeURIComponent(buildCustomerWhatsAppText(r, pharmacy))
                    window.open(`https://wa.me/${phone}?text=${text}`, '_blank', 'noopener,noreferrer')
                  }}
                  className="w-full flex items-center justify-center gap-2 bg-emerald-500 hover:bg-emerald-600 active:bg-emerald-700 text-white text-sm font-bold px-3 py-2.5 rounded-xl transition-colors mb-2 shadow-sm"
                >
                  <svg className="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
                  </svg>
                  واتساب للعميل
                  <span className="text-emerald-200 text-xs font-normal" dir="ltr">({r.contact_phone})</span>
                </button>

                {/* Print customer receipt */}
                <button
                  onClick={() => printCustomerReceipt(r, pharmacy)}
                  className="w-full flex items-center justify-center gap-2 border-2 border-emerald-400 text-emerald-700 hover:bg-emerald-50 active:bg-emerald-100 text-sm font-bold px-3 py-2 rounded-xl transition-colors"
                >
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
                  </svg>
                  إيصال العميل
                </button>
              </div>
            )}
          </div>

          {/* All items + per-item stock — unified panel */}
          <AllItemsPanel r={r} onRefresh={invalidate} />

          {/* Dates */}
          <div className="card">
            <h3 className="font-bold text-gray-400 mb-3 text-xs uppercase tracking-wide">التواريخ</h3>
            <div className="space-y-2.5">
              <div>
                <div className="text-xs text-gray-400">موعد الوصول المتوقع</div>
                <div className="text-sm font-medium text-gray-700">{formatDate(r.expected_arrival_date)}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">تاريخ المتابعة</div>
                <div className={`text-sm font-medium ${r.follow_up_date ? 'text-orange-600' : 'text-gray-700'}`}>
                  {formatDate(r.follow_up_date)}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-400">آخر تحديث</div>
                <div className="text-sm text-gray-500">{timeAgo(r.updated_at)}</div>
              </div>
            </div>
          </div>

          {/* Order source & fulfillment */}
          {(r.order_source || r.fulfillment_method) && (
            <div className="card">
              <h3 className="font-bold text-gray-400 mb-3 text-xs uppercase tracking-wide">تفاصيل الطلب</h3>
              <div className="space-y-2">
                {r.order_source && (
                  <div>
                    <div className="text-xs text-gray-400">مصدر الطلب</div>
                    <div className="text-sm font-medium text-gray-700">{ORDER_SOURCE_LABELS[r.order_source] || r.order_source}</div>
                  </div>
                )}
                {r.fulfillment_method && (
                  <div>
                    <div className="text-xs text-gray-400">طريقة التسليم</div>
                    <div className="text-sm font-medium text-gray-700">{FULFILLMENT_LABELS[r.fulfillment_method] || r.fulfillment_method}</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Assignment */}
          {r.assigned_to_name && (
            <div className="card">
              <h3 className="font-bold text-gray-400 mb-2 text-xs uppercase tracking-wide">مسند إلى</h3>
              <div className="flex items-center gap-2">
                <InitialsAvatar name={r.assigned_to_name} />
                <span className="text-sm font-medium text-gray-700">{r.assigned_to_name}</span>
              </div>
            </div>
          )}

          {/* Customer History Panel */}
          <CustomerHistoryPanel
            reservationId={r.id}
            customerId={r.customer_id || r.customer}
          />
        </div>
      </div>
    </div>
  )
}
