/**
 * DashboardPage.jsx
 * Route: /dashboard
 * All roles — content scoped by role on the backend.
 *
 * Sections:
 *  1.  Top action bar — greeting + quick-action buttons
 *  2.  Hero KPI strip — 6 top-line numbers
 *  3.  Reservation status funnel
 *  4.  Follow-ups due today — live expandable panel
 *  5.  Transfers panel — pending + flagged (admin/CC/purchasing)
 *  6.  Branch active breakdown (admin/CC only)
 *  7.  Sales mini-stats
 *  8.  Stock alerts
 *  9.  Sync status
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { dashboardApi, syncApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Design tokens (match tailwind.config brand palette)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const BRAND  = '#1B6B3A'
const GREEN  = '#10b981'
const BLUE   = '#3b82f6'
const ORANGE = '#f59e0b'
const RED    = '#ef4444'
const INDIGO = '#6366f1'
const PURPLE = '#8b5cf6'
const GRAY   = '#9ca3af'

const STATUS_CFG = {
  pending:   { label: 'قيد الانتظار',   color: GRAY,   bg: '#f9fafb' },
  available: { label: 'المخزون متاح',    color: ORANGE, bg: '#fffbeb' },
  contacted: { label: 'تم التواصل',      color: BLUE,   bg: '#eff6ff' },
  confirmed: { label: 'مؤكد — قادم',    color: INDIGO, bg: '#f5f3ff' },
  fulfilled: { label: 'تم التسليم',      color: GREEN,  bg: '#f0fdf4' },
}

const PRIORITY_CFG = {
  urgent:  { label: 'عاجل 🔴',    cls: 'bg-red-100 text-red-700' },
  chronic: { label: 'مزمن 💊',    cls: 'bg-purple-100 text-purple-700' },
  normal:  { label: 'عادي',       cls: 'bg-gray-100 text-gray-500' },
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Primitive components
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function Card({ children, className = '', style = {} }) {
  return (
    <div
      className={`bg-white rounded-2xl shadow-sm border border-gray-100 p-5 ${className}`}
      style={style}
    >
      {children}
    </div>
  )
}

function SectionTitle({ icon, children, action }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-sm font-bold text-gray-700 flex items-center gap-2">
        <span className="w-1 h-4 rounded-full inline-block" style={{ background: BRAND }} />
        {icon && <span>{icon}</span>}
        {children}
      </h2>
      {action}
    </div>
  )
}

function SkeletonStrip({ cols = 6 }) {
  return (
    <div className={`grid grid-cols-2 md:grid-cols-${cols} gap-3`}>
      {Array.from({ length: cols }).map((_, i) => (
        <div key={i} className="h-24 bg-gray-100 rounded-2xl animate-pulse" />
      ))}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 2. Hero KPI Card
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function HeroKpi({ icon, label, value, sub, color, bg, borderColor, onClick, pulse }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-2xl p-4 text-right w-full border transition-all duration-150 ${
        onClick ? 'hover:shadow-md hover:scale-[1.02] cursor-pointer' : 'cursor-default'
      } ${pulse ? 'animate-pulse' : ''}`}
      style={{ background: bg || '#f9fafb', borderColor: borderColor || (color + '33') }}
    >
      <div className="flex items-start justify-between mb-2">
        <span className="text-xl">{icon}</span>
        {pulse && (
          <span
            className="w-2 h-2 rounded-full animate-pulse flex-shrink-0 mt-1"
            style={{ background: color }}
          />
        )}
      </div>
      <div className="text-3xl font-black tabular-nums" style={{ color }}>
        {value ?? '—'}
      </div>
      <div className="text-xs font-semibold mt-1 truncate" style={{ color }}>
        {label}
      </div>
      {sub && (
        <div className="text-xs mt-0.5 opacity-60 truncate" style={{ color }}>
          {sub}
        </div>
      )}
    </button>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 3. Status Funnel
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function StatusFunnel({ funnel, onClick }) {
  const max = Math.max(...(funnel || []).map(f => f.count), 1)
  if (!funnel || funnel.length === 0) return null

  return (
    <div className="space-y-2">
      {funnel.map(f => {
        const cfg = STATUS_CFG[f.status] || {}
        const pct = Math.round((f.count / max) * 100)
        return (
          <button
            key={f.status}
            onClick={() => onClick?.(f.status)}
            className="w-full flex items-center gap-3 group text-right hover:opacity-80 transition-opacity"
          >
            <div className="w-20 text-xs font-semibold text-right shrink-0 truncate"
              style={{ color: cfg.color }}>
              {cfg.label}
            </div>
            <div className="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: cfg.color }}
              />
            </div>
            <div className="w-10 text-xs font-black tabular-nums text-right shrink-0"
              style={{ color: cfg.color }}>
              {f.count}
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 4. Follow-ups today panel
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function FollowUpPanel({ navigate }) {
  const [expanded, setExpanded] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['followups-today'],
    queryFn: () => dashboardApi.followups().then(r => r.data),
    refetchInterval: 60_000,
    enabled: expanded,
  })

  const count = data?.count ?? 0
  const results = data?.results ?? []

  return (
    <div className="border border-orange-200 rounded-2xl overflow-hidden bg-orange-50">
      {/* Header — always visible, acts as toggle */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-right hover:bg-orange-100 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-xl">📅</span>
          <div>
            <div className="font-bold text-orange-800 text-sm">
              متابعة اليوم
            </div>
            <div className="text-xs text-orange-600">
              {format(new Date(), 'EEEE، d MMMM', { locale: ar })}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {!expanded && (
            <span
              className="text-2xl font-black tabular-nums"
              style={{ color: ORANGE }}
            >
              {data?.count ?? '...'}
            </span>
          )}
          <span className="text-orange-400 text-lg">
            {expanded ? '▲' : '▼'}
          </span>
        </div>
      </button>

      {/* Expanded list */}
      {expanded && (
        <div className="border-t border-orange-200">
          {isLoading && (
            <div className="px-5 py-4 text-sm text-orange-600 animate-pulse">
              جارٍ التحميل...
            </div>
          )}

          {!isLoading && results.length === 0 && (
            <div className="px-5 py-8 text-center">
              <div className="text-3xl mb-2">✅</div>
              <div className="text-sm text-orange-700 font-medium">
                لا توجد متابعات مطلوبة اليوم
              </div>
            </div>
          )}

          {!isLoading && results.length > 0 && (
            <div className="divide-y divide-orange-100 max-h-72 overflow-y-auto">
              {results.map(r => {
                const pri = PRIORITY_CFG[r.priority] || PRIORITY_CFG.normal
                const sc  = STATUS_CFG[r.status] || {}
                return (
                  <button
                    key={r.id}
                    onClick={() => navigate(`/reservations/${r.id}`)}
                    className="w-full flex items-start gap-3 px-5 py-3 hover:bg-orange-100 transition-colors text-right"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-gray-800 text-sm truncate">
                        {r.item_name}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2 flex-wrap">
                        <span>👤 {r.customer_name}</span>
                        <span className="font-mono" dir="ltr">{r.contact_phone}</span>
                        <span>🏥 {r.branch_name}</span>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <span className={`badge text-xs ${pri.cls}`}>{pri.label}</span>
                      <span
                        className="text-xs font-semibold px-1.5 py-0.5 rounded"
                        style={{ color: sc.color, background: sc.bg }}
                      >
                        {r.status_label}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}

          {!isLoading && results.length > 0 && (
            <div className="px-5 py-2.5 border-t border-orange-100">
              <button
                onClick={() => navigate('/reservations')}
                className="text-xs text-orange-700 font-semibold hover:underline"
              >
                عرض كل الحجوزات ←
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 5. Transfers alert strip
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function TransferStrip({ transfers, navigate }) {
  if (!transfers) return null
  const { pending, flagged, this_week, incoming_to_my_branch } = transfers
  if (!pending && !flagged && !incoming_to_my_branch) return null

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
      {pending > 0 && (
        <button
          onClick={() => navigate('/transfers?status=sent')}
          className="flex items-center gap-3 rounded-xl border border-yellow-200 bg-yellow-50 px-4 py-3 hover:bg-yellow-100 transition-colors text-right"
        >
          <span className="text-2xl shrink-0">⏳</span>
          <div>
            <div className="text-2xl font-black text-yellow-700 tabular-nums">{pending}</div>
            <div className="text-xs font-semibold text-yellow-600">تحويل بانتظار الرد</div>
          </div>
        </button>
      )}
      {flagged > 0 && (
        <button
          onClick={() => navigate('/transfers?flagged_no_sale=true')}
          className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 hover:bg-red-100 transition-colors text-right"
        >
          <span className="text-2xl shrink-0">⚠️</span>
          <div>
            <div className="text-2xl font-black text-red-700 tabular-nums">{flagged}</div>
            <div className="text-xs font-semibold text-red-600">تحويل غير مُصرَّف</div>
          </div>
        </button>
      )}
      {incoming_to_my_branch > 0 && (
        <button
          onClick={() => navigate('/transfers')}
          className="flex items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 hover:bg-blue-100 transition-colors text-right"
        >
          <span className="text-2xl shrink-0">📥</span>
          <div>
            <div className="text-2xl font-black text-blue-700 tabular-nums">{incoming_to_my_branch}</div>
            <div className="text-xs font-semibold text-blue-600">طلب وارد لفرعك</div>
          </div>
        </button>
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 6. Branch breakdown bar table
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function BranchBreakdown({ byBranch, navigate }) {
  if (!byBranch || byBranch.length === 0) return null
  const max = Math.max(...byBranch.map(b => b.count), 1)

  return (
    <div className="space-y-2">
      {byBranch.map((b, i) => {
        const pct = Math.round((b.count / max) * 100)
        return (
          <button
            key={b['branch__id'] || i}
            onClick={() => navigate(`/reservations?branch=${b['branch__id']}`)}
            className="w-full flex items-center gap-3 hover:opacity-80 transition-opacity text-right group"
          >
            <div className="w-28 text-xs font-semibold text-gray-700 truncate text-right shrink-0">
              {b.branch_name}
            </div>
            <div className="flex-1 h-4 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: BRAND }}
              />
            </div>
            <span className="text-xs font-black tabular-nums w-8 text-right shrink-0"
              style={{ color: BRAND }}>
              {b.count}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 7. Sales mini
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function SalesMini({ sales }) {
  if (!sales) return null
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="bg-gray-50 rounded-xl p-3 text-center">
        <div className="text-2xl font-black text-gray-800 tabular-nums">
          {sales.invoices_7d?.toLocaleString('ar-EG')}
        </div>
        <div className="text-xs text-gray-500 mt-0.5">فاتورة — آخر 7 أيام</div>
      </div>
      <div className="rounded-xl p-3 text-center" style={{ background: '#f0f9f4' }}>
        <div className="text-2xl font-black tabular-nums" style={{ color: BRAND }}>
          {sales.revenue_7d?.toLocaleString('ar-EG', { maximumFractionDigits: 0 })}
        </div>
        <div className="text-xs mt-0.5" style={{ color: BRAND }}>ج.م — آخر 7 أيام</div>
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 8. Stock alerts list
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function StockAlerts({ alerts }) {
  if (!alerts || alerts.length === 0) return (
    <div className="text-center py-6 text-gray-300 text-sm">
      لا توجد تنبيهات مخزون منخفض
    </div>
  )
  return (
    <div className="divide-y divide-gray-50">
      {alerts.map((a, i) => (
        <div key={i} className="flex items-center justify-between py-2.5 text-sm">
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-gray-800 text-xs truncate">{a.item_name}</div>
            <div className="text-gray-400 text-xs mt-0.5">{a.branch_name}</div>
          </div>
          <span
            className="badge shrink-0 mr-3"
            style={{
              background: a.quantity <= 1 ? '#fef2f2' : '#fff7ed',
              color:      a.quantity <= 1 ? RED : ORANGE,
            }}
          >
            {a.quantity} وحدة
          </span>
        </div>
      ))}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 9. Sync status widget
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function SyncWidget({ syncStatus }) {
  const ok  = syncStatus?.status === 'success'
  const run = syncStatus?.status === 'running'
  const err = syncStatus?.status === 'failed'

  return (
    <div
      className="flex items-center gap-3 rounded-xl p-3 border"
      style={{
        background: ok  ? '#f0fdf4' : err ? '#fef2f2' : '#f9fafb',
        borderColor: ok ? '#bbf7d0' : err ? '#fecaca' : '#e5e7eb',
      }}
    >
      <div
        className={`w-3 h-3 rounded-full shrink-0 ${run ? 'animate-pulse' : ''}`}
        style={{ background: ok ? GREEN : run ? ORANGE : err ? RED : GRAY }}
      />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-semibold text-gray-800">
          {ok  ? 'المزامنة تعمل' :
           run ? 'جارٍ المزامنة...' :
           err ? 'فشلت المزامنة' :
           'لم تتم مزامنة بعد'}
        </div>
        {syncStatus?.last_at && (
          <div className="text-xs text-gray-500 mt-0.5">
            {formatDistanceToNow(new Date(syncStatus.last_at), { locale: ar, addSuffix: true })}
            {syncStatus.records > 0 && ` · ${syncStatus.records.toLocaleString('ar-EG')} سجل`}
          </div>
        )}
      </div>
      {syncStatus?.duration && (
        <span className="text-xs text-gray-400 shrink-0">{syncStatus.duration}ث</span>
      )}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Main Page
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function DashboardPage() {
  const navigate  = useNavigate()
  const { user }  = useAuthStore()

  const { data, isLoading } = useQuery({
    queryKey: ['dashboardSummary'],
    queryFn:  () => dashboardApi.summary().then(r => r.data),
    refetchInterval: 90_000,
  })

  const { data: syncStatus } = useQuery({
    queryKey: ['syncStatus'],
    queryFn:  () => syncApi.status().then(r => r.data),
    refetchInterval: 30_000,
  })

  const isAdminOrCC = ['admin', 'call_center', 'purchasing'].includes(user?.role)

  const r  = data?.reservations || {}
  const tr = data?.transfers    || {}
  const s  = data?.sales        || {}
  const c  = data?.customers    || {}
  const now = new Date()

  // ── Greeting ──────────────────────────────────────────────────
  const hour = now.getHours()
  const greeting =
    hour < 12 ? 'صباح الخير' :
    hour < 17 ? 'مساء الخير' : 'مساء النور'

  return (
    <div className="min-h-full bg-gray-50 pb-10" dir="rtl">

      {/* ── Top bar ─────────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-black text-gray-900">
              {greeting}، {user?.full_name?.split(' ')[0] || user?.username} 👋
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">
              {format(now, 'EEEE، d MMMM yyyy', { locale: ar })}
              {user?.branch_name && <span className="mr-2">· {user.branch_name}</span>}
            </p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => navigate('/reservations')}
              className="btn-secondary text-sm flex items-center gap-1.5"
            >
              📋 الحجوزات
            </button>
            <button
              onClick={() => navigate('/transfers')}
              className="btn-secondary text-sm flex items-center gap-1.5"
            >
              🔀 التحويلات
            </button>
            <button
              onClick={() => navigate('/reservations/new')}
              className="btn-primary text-sm flex items-center gap-1.5"
            >
              + حجز جديد
            </button>
          </div>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">

        {/* ── 2. Hero KPI Strip ──────────────────────────────────── */}
        {isLoading ? (
          <SkeletonStrip cols={6} />
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            <HeroKpi
              icon="📋" label="نشط الآن"
              value={r.active_total}
              sub="حجز قيد المعالجة"
              color={BRAND} bg="#f0f9f4"
              onClick={() => navigate('/reservations')}
            />
            <HeroKpi
              icon="📦" label="المخزون متاح"
              value={r.available}
              sub="ينتظر اتصالاً بالعميل"
              color={ORANGE} bg="#fffbeb"
              onClick={() => navigate('/reservations?status=available')}
              pulse={r.available > 0}
            />
            <HeroKpi
              icon="📅" label="متابعة اليوم"
              value={r.follow_ups_today}
              sub="مواعيد محددة"
              color={BLUE} bg="#eff6ff"
              onClick={() => navigate('/reservations')}
              pulse={r.follow_ups_today > 0}
            />
            <HeroKpi
              icon="🔴" label="عاجل نشط"
              value={r.urgent_active}
              color={RED} bg="#fef2f2"
              onClick={() => navigate('/reservations?priority=urgent')}
              pulse={r.urgent_active > 0}
            />
            <HeroKpi
              icon="✅" label="تم التسليم"
              value={r.fulfilled_this_week}
              sub="هذا الأسبوع"
              color={GREEN} bg="#f0fdf4"
            />
            <HeroKpi
              icon="👥" label="إجمالي العملاء"
              value={c.total?.toLocaleString('ar-EG')}
              sub={`${c.new_this_month ?? 0} جديد هذا الشهر`}
              color={INDIGO} bg="#f5f3ff"
            />
          </div>
        )}

        {/* ── Stale warning banner ────────────────────────────────── */}
        {!isLoading && r.stale_7d > 0 && (
          <button
            onClick={() => navigate('/reservations?status=pending')}
            className="w-full flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 hover:bg-amber-100 transition-colors text-right"
          >
            <span className="text-xl shrink-0">⏰</span>
            <div className="flex-1">
              <span className="font-bold text-amber-800 text-sm">
                {r.stale_7d} حجز عالق
              </span>
              <span className="text-amber-600 text-xs mr-2">
                — بدون تحديث منذ أكثر من 7 أيام. يحتاج مراجعة.
              </span>
            </div>
            <span className="text-amber-400 text-sm shrink-0">← مراجعة</span>
          </button>
        )}

        {/* ── 4. Follow-ups today ─────────────────────────────────── */}
        <FollowUpPanel navigate={navigate} />

        {/* ── 5. Transfer alerts ──────────────────────────────────── */}
        {!isLoading && (tr.pending > 0 || tr.flagged > 0 || tr.incoming_to_my_branch > 0) && (
          <div>
            <SectionTitle icon="🔀">
              تنبيهات التحويل
            </SectionTitle>
            <TransferStrip transfers={tr} navigate={navigate} />
          </div>
        )}

        {/* ── Main two-column layout ──────────────────────────────── */}
        <div className="grid lg:grid-cols-3 gap-5">

          {/* Left 2/3 */}
          <div className="lg:col-span-2 space-y-5">

            {/* Status funnel */}
            <Card>
              <SectionTitle
                icon="📊"
                action={
                  <button
                    onClick={() => navigate('/reservations')}
                    className="text-xs text-brand-600 hover:underline"
                  >
                    عرض الكل ←
                  </button>
                }
              >
                مسار الحجوزات — حسب الحالة
              </SectionTitle>
              {isLoading ? (
                <div className="space-y-2">
                  {[1,2,3,4,5].map(i => (
                    <div key={i} className="h-5 bg-gray-100 rounded-full animate-pulse" />
                  ))}
                </div>
              ) : (
                <StatusFunnel
                  funnel={data?.status_funnel}
                  onClick={status => navigate(`/reservations?status=${status}`)}
                />
              )}
            </Card>

            {/* Branch breakdown (admin/CC only) */}
            {!isLoading && isAdminOrCC && (data?.by_branch?.length ?? 0) > 0 && (
              <Card>
                <SectionTitle icon="🏥">
                  الحجوزات النشطة بالفروع
                </SectionTitle>
                <BranchBreakdown byBranch={data.by_branch} navigate={navigate} />
              </Card>
            )}

            {/* Secondary KPI row */}
            {!isLoading && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: 'تم التواصل',    value: r.contacted,  color: BLUE,   bg: '#eff6ff',  status: 'contacted' },
                  { label: 'مؤكد — قادم',  value: r.confirmed,  color: INDIGO, bg: '#f5f3ff',  status: 'confirmed' },
                  { label: 'مريض مزمن 💊', value: r.chronic_active, color: PURPLE, bg: '#f5f3ff', status: null },
                  { label: 'قيد الانتظار', value: r.pending,    color: GRAY,   bg: '#f9fafb',  status: 'pending' },
                ].map((k, i) => (
                  <button
                    key={i}
                    onClick={k.status ? () => navigate(`/reservations?status=${k.status}`) : undefined}
                    className={`rounded-xl p-3 border text-right transition-shadow ${k.status ? 'hover:shadow-sm cursor-pointer' : 'cursor-default'}`}
                    style={{ background: k.bg, borderColor: k.color + '33' }}
                  >
                    <div className="text-2xl font-black tabular-nums" style={{ color: k.color }}>
                      {k.value ?? 0}
                    </div>
                    <div className="text-xs font-semibold mt-0.5 truncate" style={{ color: k.color }}>
                      {k.label}
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Sales */}
            {!isLoading && (
              <Card>
                <SectionTitle icon="💰">المبيعات — آخر 7 أيام</SectionTitle>
                <SalesMini sales={s} />
              </Card>
            )}
          </div>

          {/* Right 1/3 */}
          <div className="space-y-5">

            {/* Stock alerts */}
            <Card>
              <SectionTitle
                icon="⚠️"
                action={
                  (data?.stock_alerts?.length ?? 0) > 0 ? (
                    <span
                      className="text-xs font-bold px-2 py-0.5 rounded-full"
                      style={{ background: '#fff7ed', color: ORANGE }}
                    >
                      {data.stock_alerts.length}
                    </span>
                  ) : null
                }
              >
                مخزون منخفض
              </SectionTitle>
              {isLoading ? (
                <div className="space-y-2">
                  {[1,2,3].map(i => <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />)}
                </div>
              ) : (
                <StockAlerts alerts={data?.stock_alerts} />
              )}
            </Card>

            {/* Sync */}
            <Card>
              <SectionTitle icon="⟳">المزامنة مع SOFTECH</SectionTitle>
              <SyncWidget syncStatus={data?.sync || syncStatus} />
              {data?.sync?.last_at && (
                <div className="text-xs text-gray-400 mt-2 text-center">
                  آخر تحديث للبيانات:{' '}
                  {format(new Date(data.sync.last_at), 'HH:mm', { locale: ar })}
                </div>
              )}
            </Card>

            {/* Purchasing shortcut (admin/purchasing only) */}
            {isAdminOrCC && user?.role !== 'call_center' && (
              <button
                onClick={() => navigate('/purchasing')}
                className="w-full rounded-2xl p-4 border-2 text-right transition-all hover:shadow-md"
                style={{ borderColor: BRAND + '44', background: '#f0f9f4' }}
              >
                <div className="text-2xl mb-1">📊</div>
                <div className="font-bold text-sm" style={{ color: BRAND }}>
                  لوحة المشتريات
                </div>
                <div className="text-xs mt-0.5 opacity-70" style={{ color: BRAND }}>
                  تحليلات التحويل والأوردر الدوري ←
                </div>
              </button>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
