/**
 * CustomerDetailPage.jsx
 * Route: /customers/:id
 *
 * Layout:
 *  Left column (2/3):
 *    - Tabs: Timeline | Purchases | Reservations | Top Items
 *  Right column (1/3):
 *    - Hero card: name, type, KPIs
 *    - Contact info
 *    - Chronic conditions (editable inline)
 *    - SOFTECH notes
 *    - Quick actions
 */

import { useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { customersApi, recommendationsApi, loyaltyApi } from '../api/client'
import { tint } from '../theme/theme'
import useAuthStore from '../store/authStore'
import { format, formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s => s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Design tokens
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const BRAND  = 'rgb(var(--c-brand-600))'
const GREEN  = '#10b981'
const BLUE   = '#3b82f6'
const ORANGE = '#f59e0b'
const RED    = '#ef4444'
const INDIGO = '#6366f1'
const GRAY   = '#9ca3af'

const STATUS_CFG = {
  pending:   { label: 'قيد الانتظار',  dot: GRAY,   bg: '#f9fafb', text: '#6b7280' },
  available: { label: 'المخزون متاح',  dot: ORANGE, bg: '#fffbeb', text: '#92400e' },
  contacted: { label: 'تم التواصل',    dot: BLUE,   bg: '#eff6ff', text: '#1e40af' },
  confirmed: { label: 'مؤكد — قادم',  dot: INDIGO, bg: '#f5f3ff', text: '#3730a3' },
  fulfilled: { label: 'تم التسليم',    dot: GREEN,  bg: '#f0fdf4', text: '#166534' },
  cancelled: { label: 'ملغي',          dot: RED,    bg: '#fef2f2', text: '#991b1b' },
  expired:   { label: 'منتهي',         dot: RED,    bg: '#fef2f2', text: '#991b1b' },
}

const PRIORITY_CFG = {
  urgent:  { label: 'عاجل 🔴',  cls: 'bg-red-100 text-red-700' },
  chronic: { label: 'مزمن 💊',  cls: 'bg-purple-100 text-purple-700' },
  normal:  { label: 'عادي',      cls: 'bg-gray-100 text-gray-500' },
}

const TYPE_COLOR = {
  blue:  { bg: '#eff6ff', text: '#1e40af', border: '#bfdbfe' },
  green: { bg: '#f0fdf4', text: '#166534', border: '#bbf7d0' },
  gray:  { bg: '#f9fafb', text: '#374151', border: '#e5e7eb' },
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function fmtDate(d, fmt = 'd MMM yyyy') {
  if (!d) return '—'
  try { return toLatinDigits(format(new Date(d), fmt, { locale: ar })) } catch { return String(d) }
}

function timeAgo(d) {
  if (!d) return ''
  try { return toLatinDigits(formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })) } catch { return '' }
}

function initials(name) {
  return (name || '?').split(' ').map(w => w[0]).slice(0, 2).join('')
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Shared primitives
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function Card({ children, className = '', style = {} }) {
  return (
    <div className={`bg-white rounded-2xl shadow-sm border border-gray-100 p-5 ${className}`} style={style}>
      {children}
    </div>
  )
}

function InfoRow({ label, value, mono }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 border-b border-gray-50 last:border-0">
      <span className="text-xs text-gray-400 shrink-0">{label}</span>
      <span className={`text-xs font-medium text-gray-700 text-right ${mono ? 'font-mono' : ''}`}>
        {value || '—'}
      </span>
    </div>
  )
}

function Tab({ label, active, onClick, count }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap ${
        active
          ? 'border-brand-600 text-brand-700'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-200'
      }`}
    >
      {label}
      {count !== undefined && count !== null && (
        <span className={`badge text-xs ${active ? 'bg-brand-100 text-brand-700' : 'bg-gray-100 text-gray-400'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

function EmptyState({ icon, title, sub }) {
  return (
    <div className="flex flex-col items-center justify-center py-14 text-center">
      <div className="text-5xl mb-3">{icon}</div>
      <div className="text-sm font-semibold text-gray-500">{title}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Timeline — notes + reservations merged, sorted by date
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function TimelineEntry({ entry, navigate, onDeleteNote }) {
  if (entry.type === 'note') {
    const n = entry.data
    return (
      <div className="flex gap-3 py-3">
        {/* Avatar */}
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
          style={{ background: BRAND }}
        >
          {initials(n.created_by_name || '؟')}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-sm font-semibold text-gray-800">{n.created_by_name || 'موظف'}</span>
            {n.created_by_branch && (
              <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                {n.created_by_branch}
              </span>
            )}
            <span className="text-xs text-gray-400 mr-auto">{timeAgo(n.created_at)}</span>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl rounded-tr-sm px-4 py-3 shadow-sm">
            <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{n.note}</p>
          </div>
          {onDeleteNote && (
            <button
              onClick={() => onDeleteNote(n.id)}
              className="text-xs text-gray-300 hover:text-red-400 mt-1 transition-colors"
            >
              حذف
            </button>
          )}
        </div>
      </div>
    )
  }

  if (entry.type === 'reservation') {
    const r = entry.data
    const sc = STATUS_CFG[r.status] || {}
    const pr = PRIORITY_CFG[r.priority] || PRIORITY_CFG.normal
    return (
      <div className="flex gap-3 py-3">
        <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-base flex-shrink-0">
          📋
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-400 mb-1">{timeAgo(r.created_at)}</div>
          <button
            onClick={() => navigate(`/reservations/${r.id}`)}
            className="w-full text-right bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 hover:bg-brand-50 hover:border-brand-200 transition-colors"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-semibold text-gray-800 text-sm break-words">{r.item_name}</div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {r.branch_name} · {fmtDate(r.created_at)}
                </div>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <span
                  className="text-xs font-semibold px-2 py-0.5 rounded-full"
                  style={{ background: sc.bg, color: sc.text }}
                >
                  {sc.label}
                </span>
                <span className={`badge text-xs ${pr.cls}`}>{pr.label}</span>
              </div>
            </div>
          </button>
        </div>
      </div>
    )
  }

  return null
}

function Timeline({ notes, reservations, navigate, onDeleteNote }) {
  // Merge notes and reservation events sorted newest-first
  const events = [
    ...(notes || []).map(n => ({
      type: 'note',
      date: new Date(n.created_at),
      data: n,
    })),
    ...(reservations || []).map(r => ({
      type: 'reservation',
      date: new Date(r.created_at),
      data: r,
    })),
  ].sort((a, b) => b.date - a.date)

  if (events.length === 0) return (
    <EmptyState icon="💬" title="لا توجد أنشطة بعد" sub="الملاحظات والحجوزات ستظهر هنا" />
  )

  return (
    <div className="divide-y divide-gray-50">
      {events.map((ev, i) => (
        <TimelineEntry
          key={`${ev.type}-${ev.data.id}-${i}`}
          entry={ev}
          navigate={navigate}
          onDeleteNote={ev.type === 'note' ? onDeleteNote : undefined}
        />
      ))}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Note compose box
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function NoteCompose({ customerId, onPosted }) {
  const [text, setText] = useState('')
  const [posting, setPosting] = useState(false)
  const [error, setError] = useState('')
  const ref = useRef()

  const post = async () => {
    if (!text.trim()) return
    setPosting(true); setError('')
    try {
      await customersApi.addNote(customerId, text)
      setText('')
      onPosted()
    } catch {
      setError('حدث خطأ عند الحفظ')
    } finally { setPosting(false) }
  }

  return (
    <div className="border border-gray-200 rounded-xl p-3 mb-4">
      <textarea
        ref={ref}
        rows={2}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) post() }}
        placeholder="أضف ملاحظة، تعليق طبي، أو تحديثاً عن العميل... (Ctrl+Enter)"
        className="w-full text-sm resize-none focus:outline-none placeholder-gray-300 leading-relaxed"
      />
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-100">
        {error && <span className="text-xs text-red-500">{error}</span>}
        <div className="flex-1" />
        <span className="text-xs text-gray-300 ml-2">Ctrl+Enter</span>
        <button
          onClick={post}
          disabled={!text.trim() || posting}
          className="bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold px-3 py-1.5 rounded-lg disabled:opacity-50 transition-colors mr-2"
        >
          {posting ? 'جارٍ...' : 'إرسال'}
        </button>
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Purchases tab
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function PurchasesTab({ customerId }) {
  const [filter, setFilter] = useState('all')

  const { data: purchases, isLoading } = useQuery({
    queryKey: ['customer-purchases', customerId, filter],
    queryFn: () => customersApi.purchases(customerId, filter !== 'all' ? filter : undefined)
      .then(r => r.data),
  })

  if (isLoading) return (
    <div className="space-y-3">
      {[1,2,3].map(i => <div key={i} className="h-24 bg-gray-100 rounded-xl animate-pulse" />)}
    </div>
  )

  if (!purchases?.length) return (
    <EmptyState icon="🧾" title="لا توجد مشتريات مسجلة" sub="ستظهر هنا المشتريات المتزامنة من SOFTECH" />
  )

  const totalSpent = purchases
    .filter(p => !p.is_return)
    .reduce((s, p) => s + parseFloat(p.total_amount || 0), 0)

  return (
    <div>
      {/* Filter + summary strip */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div className="text-xs text-gray-500">
          إجمالي المشتريات:{' '}
          <strong className="text-gray-800" style={{ color: BRAND }}>
            {totalSpent.toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م
          </strong>
          {' '} في {purchases.length} فاتورة
        </div>
        <div className="flex border border-gray-200 rounded-lg overflow-hidden text-xs">
          {[
            { key: 'all',  label: 'الكل' },
            { key: '115',  label: 'مبيعات' },
            { key: '30',   label: 'مرتجعات' },
          ].map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 py-1.5 font-medium transition-colors ${
                filter === f.key ? 'text-white' : 'text-gray-500 hover:bg-gray-50'
              }`}
              style={filter === f.key ? { background: BRAND } : {}}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {purchases.map(p => (
          <div
            key={p.id}
            className={`rounded-xl border overflow-hidden ${
              p.is_return ? 'border-red-100 bg-red-50/30' : 'border-gray-100 bg-white'
            }`}
          >
            {/* Invoice header */}
            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-2">
                <span
                  className="badge text-xs"
                  style={{
                    background: p.is_return ? '#fef2f2' : '#f0fdf4',
                    color: p.is_return ? RED : GREEN,
                  }}
                >
                  {p.is_return ? 'مرتجع' : 'مبيعات'}
                </span>
                <span className="text-xs text-gray-500">{p.branch_name}</span>
                <span className="text-xs text-gray-300">·</span>
                <span className="text-xs text-gray-400 font-mono">{p.softech_invoice_id}</span>
              </div>
              <div className="text-right">
                <div
                  className="text-sm font-black tabular-nums"
                  style={{ color: p.is_return ? RED : BRAND }}
                >
                  {p.is_return ? '−' : ''}
                  {parseFloat(p.total_amount).toLocaleString('en-US', { maximumFractionDigits: 2 })} ج.م
                </div>
                <div className="text-xs text-gray-400">
                  {fmtDate(p.invoice_date, 'd MMM yyyy — HH:mm')}
                </div>
              </div>
            </div>

            {/* Lines */}
            {p.lines?.length > 0 && (
              <div className="border-t border-gray-100 divide-y divide-gray-50">
                {p.lines.map(l => (
                  <div key={l.id} className="flex items-center justify-between px-4 py-2 text-xs">
                    <div className="min-w-0 flex-1">
                      <span className="text-gray-700 font-medium">{l.item_name}</span>
                      {l.item_softech_id && (
                        <span className="text-gray-400 font-mono mr-1">({l.item_softech_id})</span>
                      )}
                    </div>
                    <div className="text-gray-500 shrink-0 tabular-nums">
                      {parseFloat(l.quantity).toFixed(1)} ×{' '}
                      {parseFloat(l.unit_price).toFixed(2)} ={' '}
                      <strong className="text-gray-700">
                        {parseFloat(l.line_total).toFixed(2)} ج.م
                      </strong>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Reservations tab
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ReservationsTab({ customerId, navigate }) {
  const { data: reservations, isLoading } = useQuery({
    queryKey: ['customer-reservations', customerId],
    queryFn: () => customersApi.reservations(customerId).then(r => r.data),
  })

  if (isLoading) return (
    <div className="space-y-2">
      {[1,2,3].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl animate-pulse" />)}
    </div>
  )

  if (!reservations?.length) return (
    <EmptyState icon="📋" title="لا توجد حجوزات" sub="حجوزات هذا العميل ستظهر هنا" />
  )

  return (
    <div className="space-y-2">
      {reservations.map(r => {
        const sc = STATUS_CFG[r.status] || {}
        const pr = PRIORITY_CFG[r.priority] || PRIORITY_CFG.normal
        return (
          <button
            key={r.id}
            onClick={() => navigate(`/reservations/${r.id}`)}
            className="w-full text-right rounded-xl border border-gray-100 bg-white px-4 py-3 hover:bg-brand-50 hover:border-brand-200 transition-colors"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-gray-800 text-sm truncate">
                  {r.item_name}
                </div>
                <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                  <span>🏥 {r.branch_name}</span>
                  <span>·</span>
                  <span>{fmtDate(r.created_at)}</span>
                  {r.item_softech_id && (
                    <span className="font-mono text-gray-400">({r.item_softech_id})</span>
                  )}
                </div>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <span
                  className="text-xs font-semibold px-2 py-0.5 rounded-full"
                  style={{ background: sc.bg, color: sc.text }}
                >
                  {sc.label}
                </span>
                <span className={`badge text-xs ${pr.cls}`}>{pr.label}</span>
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Top Items tab
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function TopItemsTab({ customerId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['customer-top-items', customerId],
    queryFn: () => customersApi.topItems(customerId).then(r => r.data),
  })

  if (isLoading) return (
    <div className="space-y-2">
      {[1,2,3,4,5].map(i => <div key={i} className="h-10 bg-gray-100 rounded-lg animate-pulse" />)}
    </div>
  )

  if (!data?.length) return (
    <EmptyState icon="💊" title="لا توجد بيانات كافية" sub="تظهر هنا الأدوية الأكثر شراءً" />
  )

  const maxQty = Math.max(...data.map(d => d.total_qty), 1)

  return (
    <div className="space-y-1">
      {data.map((item, i) => {
        const pct = Math.round((item.total_qty / maxQty) * 100)
        return (
          <div key={item.item_id} className="rounded-xl bg-gray-50 px-3 py-2.5 group hover:bg-brand-50 transition-colors">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-black text-gray-300 w-5 text-center shrink-0">{i + 1}</span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-gray-800 break-words">{item.item_name}</div>
                  {item.softech_id && (
                    <div className="text-xs text-gray-400 font-mono">كود: {item.softech_id}</div>
                  )}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-sm font-black tabular-nums" style={{ color: BRAND }}>
                  {item.total_qty.toFixed(1)} وحدة
                </div>
                <div className="text-xs text-gray-400 tabular-nums">
                  {item.total_spent.toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م
                </div>
              </div>
            </div>
            <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: BRAND }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Chronic Profile Tab — refill countdown per medication
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ChronicProfileTab({ customerId }) {
  const { data: profile, isLoading } = useQuery({
    queryKey: ['patient-profile', customerId],
    queryFn: () => customersApi.patientProfile(customerId).then(r => r.data),
    staleTime: 5 * 60_000,
  })

  const meds = profile?.chronic_profile || []
  const followups = profile?.active_followups || []

  if (isLoading) return (
    <div className="space-y-3 p-4">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="h-20 bg-gray-100 animate-pulse rounded-xl" />
      ))}
    </div>
  )

  if (meds.length === 0) return (
    <div className="py-10 text-center text-gray-400">
      <div className="text-3xl mb-2">💊</div>
      <div className="text-sm">لا توجد أدوية مزمنة مرتبطة بهذا العميل</div>
    </div>
  )

  return (
    <div className="space-y-3">
      {meds.map(med => {
        const days = med.days_until_refill
        const urgent = med.needs_refill_soon
        const overdue = days !== null && days < 0

        return (
          <div key={med.item_id}
            className={`rounded-xl border p-4 transition-colors
              ${overdue   ? 'border-red-200   bg-red-50'
              : urgent    ? 'border-orange-200 bg-orange-50'
              : 'border-gray-100 bg-white'}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-gray-800 leading-tight text-sm">
                  {med.item_name}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">{med.item_softech_id}</div>
              </div>
              {days !== null && (
                <span className={`shrink-0 text-xs font-bold px-2 py-1 rounded-full
                  ${overdue ? 'bg-red-100 text-red-700'
                  : urgent  ? 'bg-orange-100 text-orange-700'
                  : days <= 14 ? 'bg-yellow-100 text-yellow-700'
                  : 'bg-green-100 text-green-700'}`}>
                  {overdue ? `متأخر ${Math.abs(days)} يوم`
                  : days === 0 ? 'اليوم'
                  : `${days} يوم`}
                </span>
              )}
            </div>

            {/* Progress bar: days elapsed / duration */}
            {med.last_sale_date && med.expected_duration_days > 0 && (
              <div className="mt-2">
                <div className="flex items-center justify-between text-xs text-gray-400 mb-1">
                  <span>آخر شراء: {fmtDate(med.last_sale_date)}</span>
                  {med.refill_due && <span>الجرعة التالية: {fmtDate(med.refill_due)}</span>}
                </div>
                <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all
                      ${overdue ? 'bg-red-500' : urgent ? 'bg-orange-500' : 'bg-green-500'}`}
                    style={{
                      width: `${Math.min(100, ((med.expected_duration_days - Math.max(days || 0, 0)) / med.expected_duration_days) * 100).toFixed(1)}%`
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        )
      })}

      {/* Active follow-ups */}
      {followups.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold text-gray-500 mb-2 px-1">متابعات نشطة</div>
          {followups.map(fu => (
            <div key={fu.id} className="rounded-xl border border-indigo-100 bg-indigo-50 p-3 mb-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-indigo-800">
                  {fu.item_name || '—'}
                </span>
                <span className="text-xs text-indigo-500">{fmtDate(fu.due_date)}</span>
              </div>
              <div className="text-xs text-indigo-600 mt-0.5">{fu.status_label || fu.status}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Full Timeline Tab — ERP + reservations + demands + follow-ups
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const TIMELINE_ICONS = {
  erp_sale:    { icon: '💊', label: 'بيع', cls: 'bg-green-100 text-green-700' },
  erp_return:  { icon: '↩️', label: 'مرتجع', cls: 'bg-orange-100 text-orange-700' },
  reservation: { icon: '📋', label: 'حجز', cls: 'bg-indigo-100 text-indigo-700' },
  demand:      { icon: '🔍', label: 'طلب', cls: 'bg-blue-100 text-blue-700' },
  followup:    { icon: '📞', label: 'متابعة', cls: 'bg-purple-100 text-purple-700' },
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Churn Score sidebar card
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const CHURN_CFG = {
  low:      { label: '✅ منخفض',  color: '#059669', bg: '#f0fdf4', border: '#bbf7d0' },
  medium:   { label: '⚠️ متوسط',  color: '#d97706', bg: '#fffbeb', border: '#fde68a' },
  high:     { label: '🔴 مرتفع',  color: '#dc2626', bg: '#fef2f2', border: '#fecaca' },
  critical: { label: '🚨 حرج',    color: '#7f1d1d', bg: '#fef2f2', border: '#ef4444' },
}

function ChurnScoreCard({ customer, customerId }) {
  const qc = useQueryClient()
  const score   = customer.churn_score || 0
  const segment = customer.churn_segment || 'low'
  const cfg     = CHURN_CFG[segment] || CHURN_CFG.low
  const pct     = Math.round(score * 100)

  // Only show if we have computed churn data
  if (!customer.churn_updated_at && !customer.churn_segment) return null

  return (
    <div
      className="rounded-2xl border p-4"
      style={{ background: cfg.bg, borderColor: cfg.border }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-bold uppercase tracking-wide" style={{ color: cfg.color }}>
          خطر الانقطاع
        </h3>
        <span
          className="text-xs font-bold px-2 py-0.5 rounded-full"
          style={{ background: cfg.color + '20', color: cfg.color }}
        >
          {cfg.label}
        </span>
      </div>

      {/* Score bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs mb-1" style={{ color: cfg.color }}>
          <span>درجة الخطر</span>
          <span className="font-black text-base">{pct}%</span>
        </div>
        <div className="h-2.5 bg-white/60 rounded-full overflow-hidden border" style={{ borderColor: cfg.border }}>
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${pct}%`, background: cfg.color }}
          />
        </div>
      </div>

      {/* Segment + last visit */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-white/50 rounded-lg p-2 text-center">
          <div className="font-bold" style={{ color: cfg.color }}>{customer.segment || '—'}</div>
          <div className="text-gray-500 text-[10px] mt-0.5">شريحة CRM</div>
        </div>
        <div className="bg-white/50 rounded-lg p-2 text-center">
          <div className="font-bold text-gray-700">
            {customer.days_since_last_visit != null ? `${customer.days_since_last_visit}` : '—'}
          </div>
          <div className="text-gray-500 text-[10px] mt-0.5">يوم منذ آخر زيارة</div>
        </div>
      </div>

      {/* High/critical: show action hint */}
      {(segment === 'high' || segment === 'critical') && (
        <div className="mt-3 text-xs p-2 bg-white/70 rounded-lg text-center" style={{ color: cfg.color }}>
          ⚡ يُنصح بالتواصل مع هذا العميل فوراً
        </div>
      )}
    </div>
  )
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Health Profile Tab
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const CONDITION_LABELS = {
  has_diabetes:          { ar: 'السكري',               emoji: '🩸' },
  has_hypertension:      { ar: 'ضغط الدم',             emoji: '❤️‍🩺' },
  has_cardiovascular:    { ar: 'أمراض القلب',          emoji: '🫀' },
  has_thyroid:           { ar: 'الغدة الدرقية',        emoji: '🦋' },
  has_cholesterol:       { ar: 'ارتفاع الكوليسترول',   emoji: '🧪' },
  has_asthma:            { ar: 'الربو / التنفس',        emoji: '🫁' },
  has_psychiatric:       { ar: 'الأمراض النفسية',       emoji: '🧠' },
  has_epilepsy:          { ar: 'الصرع',                emoji: '⚡' },
  has_osteoporosis:      { ar: 'هشاشة العظام',          emoji: '🦴' },
  has_renal:             { ar: 'أمراض الكلى',           emoji: '🩺' },
  has_oncology:          { ar: 'الأورام',               emoji: '🔬' },
  has_gerd:              { ar: 'ارتجاع المريء',         emoji: '🍋' },
  has_anemia:            { ar: 'فقر الدم',              emoji: '💉' },
  has_anticoagulant:     { ar: 'مضادات التخثر',         emoji: '🩹' },
  has_immunosuppressant: { ar: 'مثبطات المناعة',        emoji: '🛡️' },
  has_other_chronic:     { ar: 'مزمن - أخرى',          emoji: '💊' },
}

function HealthProfileTab({ customerId }) {
  const { data: hp, isLoading, refetch } = useQuery({
    queryKey: ['customer-health', customerId],
    queryFn:  () => customersApi.healthProfile(customerId).then(r => r.data),
    staleTime: 5 * 60_000,
  })
  const [rebuilding, setRebuilding] = useState(false)

  const handleRebuild = async () => {
    setRebuilding(true)
    try {
      await customersApi.refreshHealth(customerId)
      refetch()
    } finally { setRebuilding(false) }
  }

  if (isLoading) return (
    <div className="p-6 space-y-3">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="h-10 bg-gray-100 animate-pulse rounded-xl" />
      ))}
    </div>
  )

  if (!hp?.exists) return (
    <div className="p-8 text-center">
      <div className="text-4xl mb-3">🏥</div>
      <div className="text-gray-500 mb-4">لم يُبنَ الملف الصحي بعد</div>
      <button
        onClick={handleRebuild}
        disabled={rebuilding}
        className="btn-primary text-sm"
      >
        {rebuilding ? 'جارٍ البناء…' : '🔄 بناء الملف الصحي الآن'}
      </button>
    </div>
  )

  const detected = Object.entries(CONDITION_LABELS).filter(([k]) => hp[k])
  const confidence = hp.condition_confidence || {}

  return (
    <div className="p-4 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-bold text-gray-800">الملف الصحي المنظّم</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            {hp.last_computed_at
              ? `آخر تحديث: ${fmtDate(hp.last_computed_at)}`
              : 'لم يُحسب بعد'}
            {hp.manually_overridden && ' · تم التعديل يدوياً'}
          </p>
        </div>
        <button
          onClick={handleRebuild}
          disabled={rebuilding}
          className="text-xs text-blue-600 hover:underline"
        >
          {rebuilding ? 'جارٍ…' : '↻ تحديث'}
        </button>
      </div>

      {/* Detected conditions */}
      {detected.length > 0 ? (
        <div>
          <div className="text-xs font-semibold text-gray-500 mb-2">الحالات المزمنة المكتشفة</div>
          <div className="grid grid-cols-2 gap-2">
            {detected.map(([key, cfg]) => {
              const conf = confidence[key.replace('has_', '')] || 0
              return (
                <div
                  key={key}
                  className="flex items-center gap-2 rounded-xl p-3 bg-orange-50 border border-orange-100"
                >
                  <span className="text-xl">{cfg.emoji}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-semibold text-orange-800 truncate">{cfg.ar}</div>
                    {conf > 0 && (
                      <div className="flex items-center gap-1 mt-0.5">
                        <div className="h-1 bg-orange-200 rounded-full flex-1 overflow-hidden">
                          <div
                            className="h-full bg-orange-500 rounded-full"
                            style={{ width: `${Math.round(conf * 100)}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-orange-600">{Math.round(conf * 100)}%</span>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        <div className="text-center py-4 text-gray-400 text-sm bg-gray-50 rounded-xl">
          لم يُكتشف أي دواء مزمن في سجل المشتريات
        </div>
      )}

      {/* Special flags */}
      <div>
        <div className="text-xs font-semibold text-gray-500 mb-2">تنبيهات خاصة</div>
        <div className="flex flex-wrap gap-2">
          {hp.pregnancy_flag    && <span className="badge bg-pink-100 text-pink-700 text-xs">🤰 حامل</span>}
          {hp.lactation_flag    && <span className="badge bg-pink-100 text-pink-700 text-xs">🍼 مرضعة</span>}
          {hp.pediatric_patient && <span className="badge bg-blue-100 text-blue-700 text-xs">👶 يشتري لطفل</span>}
          {hp.polypharmacy_flag && <span className="badge bg-red-100 text-red-700 text-xs">⚠️ أدوية متعددة (&gt;5)</span>}
          {!hp.pregnancy_flag && !hp.lactation_flag && !hp.pediatric_patient && !hp.polypharmacy_flag && (
            <span className="text-xs text-gray-400">لا تنبيهات خاصة</span>
          )}
        </div>
      </div>

      {/* Known allergies */}
      {hp.known_allergies?.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-gray-500 mb-2">الحساسيات المعروفة</div>
          <div className="flex flex-wrap gap-2">
            {hp.known_allergies.map((a, i) => (
              <span key={i} className="badge bg-red-100 text-red-700 text-xs">
                🚫 {a.ingredient || a}
              </span>
            ))}
          </div>
        </div>
      )}
      {hp.declared_allergies_text && (
        <div className="text-xs bg-red-50 border border-red-100 rounded-xl p-3 text-red-700">
          📝 {hp.declared_allergies_text}
        </div>
      )}

      {/* Active medications */}
      {hp.active_medications?.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-gray-500 mb-2">
            الأدوية النشطة ({hp.active_medications.length})
          </div>
          <div className="space-y-2">
            {hp.active_medications.map((med, i) => (
              <div key={i} className="flex items-center justify-between bg-gray-50 rounded-xl px-3 py-2">
                <div>
                  <div className="text-xs font-semibold text-gray-800">{med.item_name}</div>
                  {med.ingredient && (
                    <div className="text-[10px] text-gray-400">{med.ingredient}</div>
                  )}
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-gray-500">{med.purchase_count} مرة</div>
                  {med.last_purchase_date && (
                    <div className="text-[10px] text-gray-400">
                      آخر صرف: {fmtDate(med.last_purchase_date)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}


function FullTimelineTab({ customerId }) {
  const { data: events = [], isLoading } = useQuery({
    queryKey: ['customer-timeline', customerId],
    queryFn: () => customersApi.timeline(customerId, 60).then(r => r.data),
    staleTime: 5 * 60_000,
  })

  if (isLoading) return (
    <div className="space-y-3 p-4">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="h-14 bg-gray-100 animate-pulse rounded-xl" />
      ))}
    </div>
  )

  if (events.length === 0) return (
    <div className="py-10 text-center text-gray-400">
      <div className="text-3xl mb-2">📅</div>
      <div className="text-sm">لا توجد أحداث مسجلة بعد</div>
    </div>
  )

  return (
    <div className="relative">
      {/* Vertical line */}
      <div className="absolute top-0 bottom-0 right-6 w-px bg-gray-100" />

      <div className="space-y-0">
        {events.map((ev, i) => {
          const meta = TIMELINE_ICONS[ev.type] || { icon: '📌', label: ev.type, cls: 'bg-gray-100 text-gray-600' }
          return (
            <div key={i} className="flex gap-4 relative pl-4 py-2 group">
              {/* Icon */}
              <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center
                              text-sm z-10 border-2 border-white shadow-sm ${meta.cls}`}>
                {meta.icon}
              </div>
              {/* Content */}
              <div className="flex-1 min-w-0 pb-2 border-b border-gray-50 group-last:border-0">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-sm text-gray-800">{ev.label}</span>
                    {ev.detail && (
                      <div className="text-xs text-gray-500 mt-0.5 leading-relaxed">{ev.detail}</div>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-0.5 shrink-0">
                    {ev.amount !== undefined && ev.amount > 0 && (
                      <span className="text-xs font-semibold text-green-700">
                        {Number(ev.amount).toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م
                      </span>
                    )}
                    <span className="text-xs text-gray-400">{fmtDate(ev.date)}</span>
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Points chip — compact balance display for the right sidebar
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function PointsChip({ customerId, onDetails }) {
  const { data, isLoading } = useQuery({
    queryKey: ['loyalty-softech-balance', customerId],
    queryFn: () => loyaltyApi.softechBalance(customerId).then(r => r.data),
    staleTime: 2 * 60_000,
  })
  const balance = data?.softech_points_balance ?? 0

  return (
    <button
      onClick={onDetails}
      className="w-full flex items-center justify-between bg-gradient-to-r from-green-600 to-green-700 text-white rounded-xl px-4 py-3 hover:from-green-700 hover:to-green-800 transition-all"
      dir="rtl"
    >
      <div className="flex items-center gap-2">
        <span className="text-xl">🏆</span>
        <div className="text-right">
          <p className="text-xs text-green-200">نقاط SOFTECH</p>
          <p className="font-black text-lg leading-none">
            {isLoading ? '...' : balance.toLocaleString()}
          </p>
        </div>
      </div>
      <span className="text-green-300 text-xs">عرض التفاصيل ←</span>
    </button>
  )
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Loyalty / Points tab
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function LoyaltyTab({ customerId }) {
  const [showAdjust, setShowAdjust] = useState(false)
  const [points,     setPoints]     = useState('')
  const [reason,     setReason]     = useState('')
  const qc = useQueryClient()

  // Live SOFTECH balance
  const { data: bal, isLoading: balLoading, refetch: refetchBal } = useQuery({
    queryKey: ['loyalty-softech-balance', customerId],
    queryFn: () => loyaltyApi.softechBalance(customerId).then(r => r.data),
    staleTime: 0,
  })

  // Adjustment log
  const { data: logData, isLoading: logLoading } = useQuery({
    queryKey: ['softech-log', customerId],
    queryFn: () => loyaltyApi.softechLog(customerId).then(r => r.data),
  })

  const adjustMut = useMutation({
    mutationFn: () => loyaltyApi.adjust(customerId, { points: Number(points), reason }),
    onSuccess: () => {
      setShowAdjust(false)
      setPoints('')
      setReason('')
      refetchBal()
      qc.invalidateQueries({ queryKey: ['softech-log', customerId] })
    },
  })

  const balance = bal?.softech_points_balance ?? 0
  const hasPic  = !!bal?.softech_pic
  const logs    = logData?.results || logData || []
  const delta   = Number(points) || 0

  const fmtDt = (dt) => dt ? new Date(dt).toLocaleDateString('ar-EG', {
    year: 'numeric', month: 'short', day: 'numeric',
  }) : '—'

  return (
    <div className="space-y-5 p-1" dir="rtl">
      {/* Balance card */}
      <div className={`rounded-xl p-5 text-white ${hasPic ? 'bg-gradient-to-br from-green-600 to-green-800' : 'bg-gray-400'}`}>
        <div className="flex items-start justify-between">
          <div>
            <p className="text-green-200 text-xs mb-1">رصيد نقاط SOFTECH</p>
            {balLoading ? (
              <p className="text-2xl animate-pulse">...</p>
            ) : (
              <p className="text-4xl font-black">{balance.toLocaleString()}</p>
            )}
            <p className="text-green-200 text-sm mt-1">نقطة</p>
          </div>
          <div className="text-left space-y-2">
            {hasPic && (
              <span className="block text-green-200 font-mono text-xs bg-green-700/40 px-2 py-0.5 rounded">
                {bal.softech_pic}
              </span>
            )}
            {!hasPic && (
              <span className="block text-yellow-200 text-xs">⚠ لا يوجد PIC</span>
            )}
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            onClick={() => refetchBal()}
            disabled={balLoading}
            className="text-xs bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-40"
          >
            ↻ تحديث
          </button>
          {hasPic && (
            <button
              onClick={() => setShowAdjust(true)}
              className="text-xs bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg transition-colors"
            >
              ✎ تعديل النقاط
            </button>
          )}
        </div>
      </div>

      {/* Adjust panel */}
      {showAdjust && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-3">
          <p className="text-sm font-semibold text-amber-800">تعديل نقاط SOFTECH</p>
          <p className="text-xs text-amber-600">يؤثر على رصيد جميع الفروع عبر إجراء SOFTECH.</p>
          <input
            type="number"
            value={points}
            onChange={e => setPoints(e.target.value)}
            placeholder="نقاط (موجب أو سالب)"
            className="w-full border border-amber-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-amber-400 bg-white"
          />
          <input
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="السبب (إلزامي)"
            className="w-full border border-amber-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-amber-400 bg-white"
          />
          {delta !== 0 && (
            <p className={`text-sm font-semibold ${delta > 0 ? 'text-green-700' : 'text-red-700'}`}>
              {delta > 0 ? `إضافة ${delta.toLocaleString()} نقطة` : `خصم ${Math.abs(delta).toLocaleString()} نقطة`}
            </p>
          )}
          <div className="flex gap-2">
            <button
              onClick={() => adjustMut.mutate()}
              disabled={!points || delta === 0 || !reason.trim() || adjustMut.isPending}
              className="flex-1 bg-green-600 text-white rounded-lg px-3 py-2 text-sm disabled:opacity-50"
            >
              {adjustMut.isPending ? 'جاري التنفيذ...' : 'تنفيذ في SOFTECH'}
            </button>
            <button onClick={() => setShowAdjust(false)} className="px-3 py-2 text-sm text-gray-500">
              إلغاء
            </button>
          </div>
          {adjustMut.isError && (
            <p className="text-red-500 text-xs">{adjustMut.error?.response?.data?.detail || 'فشل التعديل'}</p>
          )}
        </div>
      )}

      {/* Adjustment history */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase mb-3">سجل التعديلات</p>
        {logLoading ? (
          <p className="text-gray-400 text-sm text-center py-4">جاري التحميل...</p>
        ) : logs.length === 0 ? (
          <p className="text-gray-400 text-sm text-center py-4">لا توجد تعديلات مسجلة</p>
        ) : (
          <div className="space-y-2">
            {logs.map(log => (
              <div key={log.id} className="flex items-center gap-3 bg-gray-50 rounded-lg px-3 py-2 text-sm">
                <span className={`text-lg font-black shrink-0 ${log.delta > 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {log.delta > 0 ? '+' : ''}{log.delta}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-gray-700 truncate">{log.reason || '—'}</p>
                  <p className="text-xs text-gray-400">
                    {log.created_by_name || 'النظام'} · {fmtDt(log.created_at)}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-xs text-gray-500">→ {log.balance_after?.toLocaleString()}</p>
                  {!log.success && <p className="text-xs text-red-500">✗</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Editable chronic conditions widget
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function ChronicConditionsWidget({ customerId, value, onSaved }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(value || '')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      await customersApi.updateConditions(customerId, text)
      onSaved(text)
      setEditing(false)
    } catch {
      /* silent */
    } finally { setSaving(false) }
  }

  return (
    <div
      className="rounded-xl p-3 border"
      style={{ background: '#fff7ed', borderColor: '#fed7aa' }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-xs font-bold" style={{ color: ORANGE }}>
          <span>💊</span> أمراض مزمنة
        </div>
        {!editing && (
          <button
            onClick={() => { setText(value || ''); setEditing(true) }}
            className="text-xs text-orange-500 hover:text-orange-700 transition-colors"
          >
            تعديل
          </button>
        )}
      </div>

      {editing ? (
        <>
          <textarea
            rows={3}
            value={text}
            onChange={e => setText(e.target.value)}
            className="w-full text-xs border border-orange-200 rounded-lg px-2 py-1.5 resize-none focus:outline-none focus:border-orange-400 bg-white"
            placeholder="مثال: سكري النوع الثاني، ارتفاع ضغط الدم..."
            autoFocus
          />
          <div className="flex gap-2 mt-2">
            <button
              onClick={save}
              disabled={saving}
              className="text-xs bg-orange-500 hover:bg-orange-600 text-white px-3 py-1 rounded-lg font-semibold disabled:opacity-50 transition-colors"
            >
              {saving ? 'حفظ...' : 'حفظ'}
            </button>
            <button
              onClick={() => setEditing(false)}
              className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1 rounded-lg border border-gray-200 transition-colors"
            >
              إلغاء
            </button>
          </div>
        </>
      ) : (
        <p className="text-xs text-orange-800 leading-relaxed whitespace-pre-line">
          {value || <span className="text-orange-300 italic">لم تُسجَّل أمراض مزمنة بعد</span>}
        </p>
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Main Page
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

// ── Unmet-demand strip (Phase 4) ──────────────────────────────────────────────
// "طلبات لم تُلبَّ" — items this customer asked for and didn't get. Renders only
// when there is unmet demand. Each row links to its demand (where the recovery
// actions live). Restock → recovery queue is automatic, surfaced in the footer.

function UnmetDemandStrip({ customerId, navigate }) {
  const { data } = useQuery({
    queryKey: ['customer-unmet-demand', customerId],
    queryFn: () => customersApi.unmetDemand(customerId).then(r => r.data),
    staleTime: 60_000,
  })
  const items = data?.items || []
  const s = data?.summary
  if (!data || (!items.length && (!s || !s.total_unmet_value))) return null

  const statusStyle = {
    lost:            'bg-red-100 text-red-700',
    available_again: 'bg-blue-100 text-blue-700',
    pending:         'bg-orange-100 text-orange-700',
    sourcing:        'bg-orange-100 text-orange-700',
  }
  const egp = v => Math.round(Number(v) || 0).toLocaleString('en-US')

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-bold text-amber-800 text-sm flex items-center gap-2">
          <span>🧩</span> طلبات لم تُلبَّ
        </h3>
        {s?.total_unmet_value > 0 && (
          <span className="text-xs font-bold text-amber-700">{egp(s.total_unmet_value)} ج.م قيمة محتملة</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {s?.lost > 0            && <span className="badge bg-red-100 text-red-700 text-[10px]">{s.lost} ضائعة</span>}
        {s?.available_again > 0 && <span className="badge bg-blue-100 text-blue-700 text-[10px]">{s.available_again} عادت للمخزون 🔔</span>}
        {s?.open > 0            && <span className="badge bg-orange-100 text-orange-700 text-[10px]">{s.open} قيد التوفير</span>}
        {s?.recovered > 0       && <span className="badge bg-green-100 text-green-700 text-[10px]">{s.recovered} مُستردة</span>}
      </div>
      <div className="space-y-1.5">
        {items.slice(0, 5).map(it => (
          <button key={it.id} onClick={() => navigate(`/demand/${it.demand_id}`)}
            className="w-full flex items-center gap-3 bg-white rounded-lg px-3 py-2 hover:bg-amber-100/50 transition-colors text-right">
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-gray-800 break-words">{it.item_name}</div>
              <div className="text-[11px] text-gray-400 font-mono">{it.softech_id} · {it.demand_number} · {it.days_waiting} يوم</div>
            </div>
            {it.line_value != null && <span className="text-xs text-gray-500 tabular-nums shrink-0">{egp(it.line_value)} ج.م</span>}
            <span className={`badge text-[10px] shrink-0 ${statusStyle[it.item_status] || 'bg-gray-100 text-gray-600'}`}>{it.status_label}</span>
          </button>
        ))}
      </div>
      {items.length > 5 && (
        <div className="text-[11px] text-amber-600 mt-2 text-center">+{items.length - 5} عنصر إضافي</div>
      )}
      <p className="text-[11px] text-amber-600 mt-2.5">
        🔔 عند عودة أي صنف للمخزون يظهر تلقائياً في قائمة الاسترداد للتواصل مع العميل.
      </p>
    </div>
  )
}

export default function CustomerDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [tab, setTab] = useState('timeline')
  const [chronicValue, setChronicValue] = useState(null)

  const { data: customer, isLoading, isError } = useQuery({
    queryKey: ['customer', id],
    queryFn: () => customersApi.get(id).then(r => r.data),
  })

  const { data: reservations } = useQuery({
    queryKey: ['customer-reservations-all', id],
    queryFn: () => customersApi.reservations(id).then(r => r.data),
  })

  const deleteNoteMutation = useMutation({
    mutationFn: (noteId) => customersApi.deleteNote(id, noteId),
    onSuccess: () => qc.invalidateQueries(['customer', id]),
  })

  if (isLoading) return (
    <div className="min-h-full bg-gray-50 p-6 animate-pulse" dir="rtl">
      <div className="max-w-6xl mx-auto grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="h-12 bg-gray-200 rounded-xl w-1/2" />
          <div className="h-64 bg-gray-100 rounded-2xl" />
        </div>
        <div className="h-96 bg-gray-100 rounded-2xl" />
      </div>
    </div>
  )

  if (isError || !customer) return (
    <div className="p-8 text-center" dir="rtl">
      <div className="text-5xl mb-3">😕</div>
      <div className="text-gray-600">لم يتم العثور على العميل</div>
      <button onClick={() => navigate('/customers')} className="btn-secondary mt-4">
        ← العودة للعملاء
      </button>
    </div>
  )

  const typeColor = TYPE_COLOR[customer.customer_type_color] || TYPE_COLOR.gray
  const chronic = chronicValue !== null ? chronicValue : customer.chronic_conditions

  const totalActive = (reservations || []).filter(r =>
    ['pending', 'available', 'contacted', 'confirmed'].includes(r.status)
  ).length

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* ── Header bar ─────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center gap-4 flex-wrap">
          <button
            onClick={() => navigate('/customers')}
            className="text-gray-400 hover:text-gray-700 p-1 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl font-black text-gray-900">{customer.name}</h1>
              <span
                className="badge text-xs font-semibold"
                style={{ background: typeColor.bg, color: typeColor.text, border: `1px solid ${typeColor.border}` }}
              >
                {customer.customer_type_label}
              </span>
              {chronic && (
                <span className="badge text-xs bg-orange-100 text-orange-700">💊 مزمن</span>
              )}
            </div>
            {customer.softech_id && (
              <div className="text-xs text-gray-400 mt-0.5 font-mono">
                كود SOFTECH: {customer.softech_id}
              </div>
            )}
          </div>

          <button
            onClick={() => navigate(`/reservations/new?customer=${customer.id}`)}
            className="btn-primary text-sm"
          >
            + حجز جديد
          </button>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-6 py-6 grid lg:grid-cols-3 gap-6">

        {/* ── Left: tabs ──────────────────────────────────────────── */}
        <div className="lg:col-span-2 flex flex-col gap-5">

          {/* Unmet-demand strip (Phase 4) — only renders when there is any */}
          <UnmetDemandStrip customerId={id} navigate={navigate} />

          {/* Tab bar */}
          <div className="border-b border-gray-200 flex gap-0 overflow-x-auto">
            <Tab label="الجدول الزمني" active={tab === 'timeline'} onClick={() => setTab('timeline')}
              count={(customer.notes?.length || 0) + (reservations?.length || 0)} />
            <Tab label="المشتريات" active={tab === 'purchases'} onClick={() => setTab('purchases')}
              count={customer.total_purchases} />
            <Tab label="الحجوزات" active={tab === 'reservations'} onClick={() => setTab('reservations')}
              count={reservations?.length} />
            <Tab label="الأدوية الأكثر شراءً" active={tab === 'top'} onClick={() => setTab('top')} />
            <Tab label="💊 المزمن" active={tab === 'chronic'} onClick={() => setTab('chronic')} />
            <Tab label="🏥 الصحة" active={tab === 'health'} onClick={() => setTab('health')} />
            <Tab label="📅 التاريخ الكامل" active={tab === 'fulltimeline'} onClick={() => setTab('fulltimeline')} />
            <Tab label="🏆 النقاط" active={tab === 'loyalty'} onClick={() => setTab('loyalty')} />
          </div>

          {/* Tab content */}
          <Card className="animate-fade-in">
            {/* Timeline */}
            {tab === 'timeline' && (
              <>
                <NoteCompose
                  customerId={id}
                  onPosted={() => qc.invalidateQueries(['customer', id])}
                />
                <Timeline
                  notes={customer.notes || []}
                  reservations={reservations || []}
                  navigate={navigate}
                  onDeleteNote={(noteId) => deleteNoteMutation.mutate(noteId)}
                />
              </>
            )}

            {/* Purchases */}
            {tab === 'purchases' && <PurchasesTab customerId={id} />}

            {/* Reservations */}
            {tab === 'reservations' && (
              <ReservationsTab customerId={id} navigate={navigate} />
            )}

            {/* Top items */}
            {tab === 'top' && <TopItemsTab customerId={id} />}

            {/* Chronic profile */}
            {tab === 'chronic' && <ChronicProfileTab customerId={id} />}

            {/* Structured health profile */}
            {tab === 'health' && <HealthProfileTab customerId={id} />}

            {/* Full ERP timeline */}
            {tab === 'fulltimeline' && <FullTimelineTab customerId={id} />}

            {/* Loyalty / Points */}
            {tab === 'loyalty' && <LoyaltyTab customerId={id} />}
          </Card>
        </div>

        {/* ── Right: sidebar ──────────────────────────────────────── */}
        <div className="flex flex-col gap-4">

          {/* KPI strip */}
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'فاتورة', value: customer.total_purchases, color: BRAND, bg: 'rgb(var(--c-brand-50))' },
              {
                label: 'إجمالي (ج.م)',
                value: customer.lifetime_value?.toLocaleString('en-US', { maximumFractionDigits: 0 }),
                color: GREEN, bg: '#f0fdf4',
              },
              {
                label: 'حجز نشط',
                value: totalActive,
                color: totalActive > 0 ? ORANGE : GRAY,
                bg: totalActive > 0 ? '#fffbeb' : '#f9fafb',
              },
            ].map((k, i) => (
              <div
                key={i}
                className="rounded-xl p-3 text-center border"
                style={{ background: k.bg, borderColor: tint(k.color, 0.2) }}
              >
                <div className="text-xl font-black tabular-nums" style={{ color: k.color }}>
                  {k.value ?? 0}
                </div>
                <div className="text-xs mt-0.5 opacity-70 truncate" style={{ color: k.color }}>
                  {k.label}
                </div>
              </div>
            ))}
          </div>

          {/* SOFTECH Points balance chip */}
          {customer.softech_pic && (
            <PointsChip customerId={id} onDetails={() => setTab('loyalty')} />
          )}

          {/* ── Churn & Intelligence Score ──────────────────────────── */}
          <ChurnScoreCard customer={customer} customerId={id} />

          {/* Contact info */}
          <Card>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
              بيانات التواصل
            </h3>
            <div className="space-y-0.5">
              <InfoRow label="الهاتف الرئيسي" value={customer.phone} mono />
              <InfoRow label="هاتف بديل"       value={customer.phone_alt} mono />
              {customer.email && <InfoRow label="البريد" value={customer.email} />}
              <InfoRow label="العنوان"          value={customer.address} />
              {customer.date_of_birth && (
                <InfoRow
                  label="تاريخ الميلاد"
                  value={fmtDate(customer.date_of_birth, 'd MMMM yyyy')}
                />
              )}
              {customer.discount_percent > 0 && (
                <InfoRow label="نسبة الخصم" value={`${customer.discount_percent}%`} />
              )}
              <InfoRow label="الفرع المفضل" value={customer.preferred_branch_name} />
            </div>
          </Card>

          {/* Chronic conditions — editable */}
          <ChronicConditionsWidget
            customerId={id}
            value={chronic}
            onSaved={(v) => {
              setChronicValue(v)
              qc.invalidateQueries(['customer', id])
            }}
          />

          {/* SOFTECH notes (read-only) */}
          {customer.notes_softech && (
            <Card>
              <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-2">
                ملاحظات SOFTECH
              </h3>
              <p className="text-xs text-gray-600 leading-relaxed bg-gray-50 rounded-lg px-3 py-2">
                {customer.notes_softech}
              </p>
            </Card>
          )}

          {/* Softech meta */}
          <Card>
            <h3 className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
              بيانات النظام
            </h3>
            <div className="space-y-0.5">
              <InfoRow label="كود SOFTECH" value={customer.softech_id} mono />
              <InfoRow label="نوع العميل"  value={customer.customer_type_label} />
              <InfoRow label="أُضيف في"    value={fmtDate(customer.created_at)} />
              <InfoRow label="آخر تحديث"   value={timeAgo(customer.updated_at)} />
            </div>
          </Card>

        </div>
      </div>
    </div>
  )
}
