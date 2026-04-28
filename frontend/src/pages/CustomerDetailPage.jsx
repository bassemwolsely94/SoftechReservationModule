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
import { customersApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { format, formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Design tokens
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const BRAND  = '#1B6B3A'
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
  try { return format(new Date(d), fmt, { locale: ar }) } catch { return String(d) }
}

function timeAgo(d) {
  if (!d) return ''
  try { return formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true }) } catch { return '' }
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
                <div className="font-semibold text-gray-800 text-sm truncate">{r.item_name}</div>
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
            {totalSpent.toLocaleString('ar-EG', { maximumFractionDigits: 0 })} ج.م
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
                  {parseFloat(p.total_amount).toLocaleString('ar-EG', { maximumFractionDigits: 2 })} ج.م
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
                  <div className="text-sm font-semibold text-gray-800 truncate">{item.item_name}</div>
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
                  {item.total_spent.toLocaleString('ar-EG', { maximumFractionDigits: 0 })} ج.م
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

          {/* Tab bar */}
          <div className="border-b border-gray-200 flex gap-0 overflow-x-auto">
            <Tab label="الجدول الزمني" active={tab === 'timeline'} onClick={() => setTab('timeline')}
              count={(customer.notes?.length || 0) + (reservations?.length || 0)} />
            <Tab label="المشتريات" active={tab === 'purchases'} onClick={() => setTab('purchases')}
              count={customer.total_purchases} />
            <Tab label="الحجوزات" active={tab === 'reservations'} onClick={() => setTab('reservations')}
              count={reservations?.length} />
            <Tab label="الأدوية الأكثر شراءً" active={tab === 'top'} onClick={() => setTab('top')} />
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
          </Card>
        </div>

        {/* ── Right: sidebar ──────────────────────────────────────── */}
        <div className="flex flex-col gap-4">

          {/* KPI strip */}
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'فاتورة', value: customer.total_purchases, color: BRAND, bg: '#f0f9f4' },
              {
                label: 'إجمالي (ج.م)',
                value: customer.lifetime_value?.toLocaleString('ar-EG', { maximumFractionDigits: 0 }),
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
                style={{ background: k.bg, borderColor: k.color + '33' }}
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
