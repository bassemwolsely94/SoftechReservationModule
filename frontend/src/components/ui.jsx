/**
 * frontend/src/components/ui.jsx
 *
 * Shared design-system primitives used across every page.
 * Import what you need:
 *   import { Skeleton, EmptyState, Toast, useToast, PageHeader } from '../components/ui'
 */

import { useState, useEffect, useCallback, createContext, useContext, useRef } from 'react'
import { createPortal } from 'react-dom'

const BRAND = '#1B6B3A'

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Skeleton loaders
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/** Single shimmer bar */
export function SkeletonLine({ w = 'w-full', h = 'h-3', className = '' }) {
  return <div className={`shimmer rounded-full ${w} ${h} ${className}`} />
}

/** Skeleton card for KPI strip */
export function SkeletonKpi() {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-4 space-y-2">
      <div className="shimmer rounded-full h-3 w-1/2" />
      <div className="shimmer rounded-full h-8 w-2/3" />
      <div className="shimmer rounded-full h-2 w-1/3" />
    </div>
  )
}

/** Skeleton table row */
export function SkeletonRow({ cols = 5 }) {
  return (
    <tr className="border-b border-gray-50">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className={`shimmer rounded-full h-3 ${i === 0 ? 'w-32' : 'w-16'}`} />
        </td>
      ))}
    </tr>
  )
}

/** Full table skeleton */
export function SkeletonTable({ rows = 6, cols = 5 }) {
  return (
    <table className="w-full">
      <tbody>
        {Array.from({ length: rows }).map((_, i) => (
          <SkeletonRow key={i} cols={cols} />
        ))}
      </tbody>
    </table>
  )
}

/** Skeleton card (generic) */
export function SkeletonCard({ lines = 3, className = '' }) {
  return (
    <div className={`card space-y-2.5 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={`shimmer rounded-full h-3 ${
            i === 0 ? 'w-1/2' : i === lines - 1 ? 'w-1/3' : 'w-full'
          }`}
        />
      ))}
    </div>
  )
}

/** Kanban card skeleton */
export function SkeletonKanbanCard() {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-3 space-y-2">
      <div className="shimmer rounded-full h-3 w-3/4" />
      <div className="shimmer rounded-full h-2 w-1/2" />
      <div className="flex gap-2 mt-1">
        <div className="shimmer rounded-full h-5 w-16" />
        <div className="shimmer rounded-full h-5 w-12" />
      </div>
    </div>
  )
}

/** Chatter entry skeleton */
export function SkeletonChatterEntry() {
  return (
    <div className="flex gap-3 py-3">
      <div className="shimmer skeleton-avatar w-8 h-8" />
      <div className="flex-1 space-y-2">
        <div className="shimmer rounded-full h-3 w-32" />
        <div className="shimmer rounded-lg h-14 w-full" />
      </div>
    </div>
  )
}

/** Full KPI strip skeleton */
export function SkeletonKpiStrip({ count = 6 }) {
  return (
    <div className={`grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-${count} gap-3 stagger`}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonKpi key={i} />
      ))}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Empty states
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const EMPTY_PRESETS = {
  reservations: {
    icon: (
      <svg className="w-16 h-16 text-gray-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <rect x="8" y="12" width="48" height="40" rx="6" strokeWidth="2.5" />
        <path d="M20 26h24M20 34h16" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="48" cy="44" r="8" fill="#f0fdf4" stroke="#1B6B3A" strokeWidth="2" />
        <path d="M44 44l3 3 5-5" stroke="#1B6B3A" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: 'لا توجد حجوزات',
    sub: 'لم يتم العثور على حجوزات تطابق هذا البحث',
  },
  customers: {
    icon: (
      <svg className="w-16 h-16 text-gray-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <circle cx="32" cy="22" r="10" strokeWidth="2.5" />
        <path d="M10 54c0-12.15 9.85-22 22-22s22 9.85 22 22" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    ),
    title: 'لا يوجد عملاء',
    sub: 'لم يتم العثور على عملاء تطابق هذا البحث',
  },
  transfers: {
    icon: (
      <svg className="w-16 h-16 text-gray-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <path d="M12 24h40M12 40h40" strokeWidth="2.5" strokeLinecap="round" />
        <path d="M40 16l12 8-12 8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M24 32l-12 8 12 8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: 'لا توجد طلبات تحويل',
    sub: 'لم يتم العثور على طلبات تحويل',
  },
  stock: {
    icon: (
      <svg className="w-16 h-16 text-gray-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <rect x="8" y="32" width="48" height="20" rx="4" strokeWidth="2.5" />
        <rect x="16" y="20" width="32" height="14" rx="3" strokeWidth="2.5" />
        <rect x="24" y="10" width="16" height="12" rx="2" strokeWidth="2.5" />
      </svg>
    ),
    title: 'لا توجد بيانات مخزون',
    sub: 'بيانات المخزون تُحدَّث تلقائياً مع كل مزامنة',
  },
  notes: {
    icon: (
      <svg className="w-16 h-16 text-gray-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <rect x="10" y="8" width="44" height="48" rx="6" strokeWidth="2.5" />
        <path d="M20 24h24M20 32h24M20 40h14" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
    ),
    title: 'لا توجد ملاحظات بعد',
    sub: 'اكتب أول ملاحظة باستخدام الحقل أعلاه',
  },
  purchases: {
    icon: (
      <svg className="w-16 h-16 text-gray-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <path d="M12 12h6l6 28h24l6-20H24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="30" cy="48" r="4" strokeWidth="2.5" />
        <circle cx="46" cy="48" r="4" strokeWidth="2.5" />
      </svg>
    ),
    title: 'لا توجد مشتريات',
    sub: 'مشتريات هذا العميل ستظهر هنا بعد المزامنة',
  },
  search: {
    icon: (
      <svg className="w-16 h-16 text-gray-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <circle cx="28" cy="28" r="16" strokeWidth="2.5" />
        <path d="M40 40l14 14" strokeWidth="2.5" strokeLinecap="round" />
        <path d="M21 28h14M28 21v14" strokeWidth="2" strokeLinecap="round" />
      </svg>
    ),
    title: 'لا توجد نتائج',
    sub: 'جرّب تعديل كلمة البحث أو مسح الفلاتر',
  },
  flagged: {
    icon: (
      <svg className="w-16 h-16 text-green-200" fill="none" viewBox="0 0 64 64" stroke="currentColor">
        <circle cx="32" cy="32" r="22" stroke="#10b981" strokeWidth="2.5" />
        <path d="M22 32l8 8 12-14" stroke="#10b981" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
    title: 'لا توجد تحويلات غير مُصرَّفة',
    sub: 'جميع التحويلات المقبولة لها مبيعات مسجلة',
  },
}

export function EmptyState({
  preset,
  icon,
  title,
  sub,
  action,
  className = '',
}) {
  const p = preset ? EMPTY_PRESETS[preset] : null
  const resolvedIcon  = icon  ?? p?.icon
  const resolvedTitle = title ?? p?.title ?? 'لا توجد بيانات'
  const resolvedSub   = sub   ?? p?.sub

  return (
    <div className={`empty-state animate-fade-in ${className}`}>
      {resolvedIcon && (
        <div className="mb-5 opacity-80">{resolvedIcon}</div>
      )}
      <p className="text-sm font-bold text-gray-500">{resolvedTitle}</p>
      {resolvedSub && (
        <p className="text-xs text-gray-400 mt-1.5 max-w-xs leading-relaxed">{resolvedSub}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Toast notification system
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const ToastContext = createContext(null)

const TOAST_ICONS = {
  success: '✅',
  error:   '❌',
  warning: '⚠️',
  info:    'ℹ️',
}

const TOAST_STYLES = {
  success: 'bg-green-600',
  error:   'bg-red-600',
  warning: 'bg-amber-500',
  info:    'bg-brand-600',
}

function ToastItem({ toast, onDismiss }) {
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      setLeaving(true)
      setTimeout(() => onDismiss(toast.id), 250)
    }, toast.duration ?? 3500)
    return () => clearTimeout(t)
  }, [toast.id, toast.duration, onDismiss])

  return (
    <div
      className={`
        pointer-events-auto flex items-start gap-3
        text-white text-sm font-medium
        px-4 py-3 rounded-xl shadow-lg min-w-64 max-w-80
        ${TOAST_STYLES[toast.type] ?? 'bg-gray-800'}
        ${leaving ? 'animate-toast-out' : 'animate-toast-in'}
      `}
    >
      <span className="text-base shrink-0">{TOAST_ICONS[toast.type]}</span>
      <div className="flex-1 min-w-0">
        <div className="font-bold text-sm">{toast.title}</div>
        {toast.message && (
          <div className="text-xs opacity-80 mt-0.5 leading-relaxed">{toast.message}</div>
        )}
      </div>
      <button
        onClick={() => { setLeaving(true); setTimeout(() => onDismiss(toast.id), 250) }}
        className="text-white/60 hover:text-white text-lg leading-none shrink-0 mt-0.5"
      >
        ✕
      </button>
    </div>
  )
}

function ToastPortal({ toasts, dismiss }) {
  const root = document.getElementById('toast-root')
  if (!root) return null
  return createPortal(
    <>
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
      ))}
    </>,
    root,
  )
}

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const add = useCallback((type, title, message, duration) => {
    const id = Date.now() + Math.random()
    setToasts(ts => [...ts, { id, type, title, message, duration }])
  }, [])

  const dismiss = useCallback((id) => {
    setToasts(ts => ts.filter(t => t.id !== id))
  }, [])

  const toast = {
    success: (title, message, duration) => add('success', title, message, duration),
    error:   (title, message, duration) => add('error',   title, message, duration),
    warning: (title, message, duration) => add('warning', title, message, duration),
    info:    (title, message, duration) => add('info',    title, message, duration),
  }

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <ToastPortal toasts={toasts} dismiss={dismiss} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    // Fallback when used outside provider
    return {
      success: (t) => console.log('✅', t),
      error:   (t) => console.error('❌', t),
      warning: (t) => console.warn('⚠️', t),
      info:    (t) => console.info('ℹ️', t),
    }
  }
  return ctx
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Spinner
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function Spinner({ size = 'sm', color = BRAND }) {
  const sz = size === 'sm' ? 'w-4 h-4' : size === 'md' ? 'w-6 h-6' : 'w-8 h-8'
  return (
    <svg
      className={`${sz} animate-spin`}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        cx="12" cy="12" r="10"
        stroke="currentColor"
        strokeWidth="3"
        strokeOpacity="0.2"
      />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        stroke={color}
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Modal shell
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = 'max-w-lg',
  footer,
}) {
  const overlayRef = useRef()

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4"
      dir="rtl"
    >
      {/* Backdrop */}
      <div
        ref={overlayRef}
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={(e) => { if (e.target === overlayRef.current) onClose() }}
      />

      {/* Sheet */}
      <div
        className={`
          relative bg-white w-full ${maxWidth}
          rounded-t-3xl sm:rounded-2xl shadow-2xl
          animate-scale-in max-h-[90dvh] flex flex-col
        `}
      >
        {/* Handle bar — mobile only */}
        <div className="sm:hidden w-10 h-1 bg-gray-200 rounded-full mx-auto mt-3 mb-1 shrink-0" />

        {/* Header */}
        <div className="flex items-start justify-between px-5 pt-4 pb-3 border-b border-gray-100 shrink-0">
          <div>
            <h3 className="font-bold text-gray-900 text-base leading-tight">{title}</h3>
            {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 p-1 rounded-lg hover:bg-gray-100 transition-colors -mt-0.5 shrink-0"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-5 py-4">
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="px-5 py-4 border-t border-gray-100 shrink-0 safe-bottom">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Page header
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function PageHeader({ title, subtitle, back, actions, children }) {
  return (
    <div className="page-header no-print">
      <div className="max-w-7xl mx-auto flex items-center gap-3 flex-wrap">
        {back && (
          <button
            onClick={back}
            className="text-gray-400 hover:text-gray-700 p-1.5 rounded-lg hover:bg-gray-100 transition-colors shrink-0"
            aria-label="رجوع"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}

        <div className="flex-1 min-w-0">
          <h1 className="text-lg sm:text-xl font-black text-gray-900 truncate">{title}</h1>
          {subtitle && (
            <p className="text-xs text-gray-400 mt-0.5 truncate">{subtitle}</p>
          )}
        </div>

        {actions && (
          <div className="flex items-center gap-2 flex-wrap shrink-0">
            {actions}
          </div>
        )}

        {children}
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Confirmation dialog
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = 'تأكيد',
  cancelLabel  = 'إلغاء',
  danger = false,
  loading = false,
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      maxWidth="max-w-sm"
      footer={
        <div className="flex gap-2">
          <button onClick={onClose} className="btn-secondary flex-1">{cancelLabel}</button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`${danger ? 'btn-danger' : 'btn-primary'} flex-1 disabled:opacity-50`}
          >
            {loading ? <Spinner size="sm" color="white" /> : confirmLabel}
          </button>
        </div>
      }
    >
      <p className="text-sm text-gray-600 leading-relaxed">{message}</p>
    </Modal>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Section title
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function SectionTitle({ icon, children, action }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <h2 className="section-title">
        <span className="w-1 h-4 rounded-full inline-block" style={{ background: BRAND }} />
        {icon && <span>{icon}</span>}
        {children}
      </h2>
      {action}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Status and priority badge helpers
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function StatusDot({ color }) {
  return (
    <span
      className="inline-block w-2 h-2 rounded-full shrink-0"
      style={{ background: color }}
    />
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Info row (key → value pair)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export function InfoRow({ label, value, mono = false }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5 border-b border-gray-50 last:border-0">
      <span className="text-xs text-gray-400 shrink-0 pt-0.5">{label}</span>
      <span className={`text-xs font-medium text-gray-700 text-right leading-relaxed ${mono ? 'font-mono' : ''}`}>
        {value || '—'}
      </span>
    </div>
  )
}
