/**
 * AuditPage.jsx  —  /audit  (admin only)
 * Two tabs: Audit Logs + Abuse Flags
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { auditApi } from '../api/client'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Design tokens ─────────────────────────────────────────────────────────────
const SEVERITY_CFG = {
  info:     { label: 'معلومة', bg: '#eff6ff', text: '#1e40af', dot: '#3b82f6' },
  warning:  { label: 'تحذير',  bg: '#fffbeb', text: '#92400e', dot: '#f59e0b' },
  critical: { label: 'حرج',   bg: '#fef2f2', text: '#991b1b', dot: '#ef4444' },
}

const FLAG_STATUS_CFG = {
  open:      { label: 'مفتوح',          bg: '#fef2f2', text: '#991b1b' },
  reviewed:  { label: 'تمت المراجعة',   bg: '#f0fdf4', text: '#166534' },
  dismissed: { label: 'تم التجاهل',     bg: '#f9fafb', text: '#6b7280' },
  escalated: { label: 'تم التصعيد',     bg: '#f5f3ff', text: '#5b21b6' },
}

const ACTION_ICONS = {
  reservation_created:        '📋',
  reservation_status_changed: '🔄',
  reservation_cancelled:      '❌',
  reservation_erp_validated:  '🔗',
  transfer_created:           '📦',
  transfer_approved:          '✅',
  transfer_rejected:          '❌',
  user_login:                 '🔑',
  user_login_failed:          '⚠️',
  sync_completed:             '⟳',
  sync_failed:                '💥',
  demand_created:             '🔍',
  demand_lost:                '💸',
  followup_auto_closed:       '💊',
  customer_created:           '👤',
  default:                    '📝',
}

function timeAgo(d) {
  if (!d) return '—'
  try { return formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true }) } catch { return d }
}

function fmtDate(d) {
  if (!d) return '—'
  try { return format(new Date(d), 'd MMM yyyy — HH:mm', { locale: ar }) } catch { return d }
}

// ── Audit Log Row ─────────────────────────────────────────────────────────────

function AuditLogRow({ log, onExpand, expanded }) {
  const icon = ACTION_ICONS[log.action] || ACTION_ICONS.default
  return (
    <>
      <tr
        onClick={() => onExpand(expanded ? null : log.id)}
        className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors">
        <td className="px-4 py-3">
          <span className="text-lg">{icon}</span>
        </td>
        <td className="px-4 py-3">
          <div className="text-xs font-semibold text-gray-700">{log.action_label}</div>
          {log.note && <div className="text-xs text-gray-400 mt-0.5 truncate max-w-48">{log.note}</div>}
        </td>
        <td className="px-4 py-3 text-xs text-gray-600">
          {log.user_display || 'النظام'}
          {log.user_role && (
            <span className="mr-1 text-gray-400">({log.user_role})</span>
          )}
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">{log.model_name} #{log.object_id}</td>
        <td className="px-4 py-3 text-xs text-gray-400 tabular-nums">{timeAgo(log.created_at)}</td>
        <td className="px-4 py-3 text-xs text-gray-300">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50 border-b border-gray-100">
          <td colSpan={6} className="px-6 py-3">
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <div className="font-bold text-gray-500 mb-1">الكيان</div>
                <div className="font-mono text-gray-700">{log.object_repr || '—'}</div>
              </div>
              {log.changes && (
                <div>
                  <div className="font-bold text-gray-500 mb-1">التغييرات</div>
                  <pre className="text-gray-700 font-mono text-xs bg-white border border-gray-200
                    rounded px-2 py-1 overflow-x-auto">
                    {JSON.stringify(log.changes, null, 2)}
                  </pre>
                </div>
              )}
              <div>
                <div className="font-bold text-gray-500 mb-1">التاريخ</div>
                <div className="text-gray-600">{fmtDate(log.created_at)}</div>
              </div>
              {log.ip_address && (
                <div>
                  <div className="font-bold text-gray-500 mb-1">عنوان IP</div>
                  <div className="font-mono text-gray-600">{log.ip_address}</div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Audit Logs Tab ────────────────────────────────────────────────────────────

function AuditLogsTab() {
  const [filters, setFilters]   = useState({ action: '', search: '' })
  const [expanded, setExpanded] = useState(null)

  const { data: logs = [], isLoading } = useQuery({
    queryKey: ['audit-logs', filters],
    queryFn:  () => auditApi.logs({
      action: filters.action || undefined,
      search: filters.search || undefined,
      page_size: 100,
    }).then(r => r.data.results || r.data),
    refetchInterval: 60_000,
  })

  const ACTION_FILTERS = [
    { value: '',                          label: 'الكل' },
    { value: 'reservation_created',       label: 'إنشاء حجوزات' },
    { value: 'reservation_status_changed',label: 'تغيير حالة' },
    { value: 'reservation_cancelled',     label: 'إلغاء حجوزات' },
    { value: 'transfer_approved',         label: 'اعتماد تحويلات' },
    { value: 'user_login',                label: 'دخول مستخدمين' },
    { value: 'user_login_failed',         label: 'محاولات دخول فاشلة' },
    { value: 'sync_completed',            label: 'مزامنة' },
  ]

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-3 mb-4 flex-wrap">
        <input
          className="input-field w-64 text-sm"
          placeholder="🔍 بحث باسم المستخدم، الكيان..."
          value={filters.search}
          onChange={e => setFilters(p => ({ ...p, search: e.target.value }))}
        />
        <select className="input-field w-52 text-sm" value={filters.action}
          onChange={e => setFilters(p => ({ ...p, action: e.target.value }))}>
          {ACTION_FILTERS.map(f => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
        <button className="btn-secondary text-sm"
          onClick={() => setFilters({ action: '', search: '' })}>
          مسح
        </button>
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          {[1,2,3,4,5].map(i => <div key={i} className="h-12 bg-gray-100 rounded-lg" />)}
        </div>
      ) : logs.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <div className="text-4xl mb-2">📋</div>
          <div>لا توجد سجلات</div>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-2 text-right text-xs text-gray-400 w-8" />
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-500">الإجراء</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-500">المستخدم</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-500">الكيان</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-500">التوقيت</th>
                <th className="px-4 py-2 w-6" />
              </tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <AuditLogRow
                  key={log.id}
                  log={log}
                  expanded={expanded === log.id}
                  onExpand={setExpanded}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Review Flag Modal ─────────────────────────────────────────────────────────

function ReviewModal({ flag, onClose, onSaved }) {
  const [newStatus, setNewStatus] = useState('reviewed')
  const [note, setNote]           = useState('')
  const [saving, setSaving]       = useState(false)
  const qc = useQueryClient()

  async function handleReview() {
    setSaving(true)
    try {
      await auditApi.reviewFlag(flag.id, { status: newStatus, note })
      qc.invalidateQueries(['abuse-flags'])
      qc.invalidateQueries(['flag-summary'])
      onSaved()
      onClose()
    } catch { } finally { setSaving(false) }
  }

  const s = SEVERITY_CFG[flag.severity] || SEVERITY_CFG.warning

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-gray-900">مراجعة الإشارة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>

        {/* Flag details */}
        <div className="rounded-xl p-4 border"
          style={{ background: s.bg, borderColor: s.dot + '44' }}>
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full" style={{ background: s.dot }} />
            <span className="font-bold text-sm" style={{ color: s.text }}>
              {flag.flag_label || flag.flag_type}
            </span>
            <span className="badge text-xs" style={{ background: s.bg, color: s.text }}>
              {s.label}
            </span>
          </div>
          <div className="text-sm text-gray-700">{flag.description}</div>
          <div className="text-xs text-gray-500 mt-1">
            {flag.staff_name} · {flag.count} حدث · {timeAgo(flag.detected_at)}
          </div>
        </div>

        {/* Review form */}
        <div>
          <label className="label text-xs">القرار</label>
          <div className="grid grid-cols-3 gap-2">
            {[
              { v: 'reviewed',  label: '✓ راجعت',       cls: 'border-green-300 bg-green-50 text-green-700' },
              { v: 'dismissed', label: '— تجاهل',        cls: 'border-gray-300 bg-gray-50 text-gray-600' },
              { v: 'escalated', label: '🚨 تصعيد',       cls: 'border-red-300 bg-red-50 text-red-700' },
            ].map(opt => (
              <button key={opt.v}
                onClick={() => setNewStatus(opt.v)}
                className={`border rounded-xl py-2 text-xs font-bold transition-all ${opt.cls}
                  ${newStatus === opt.v ? 'ring-2 ring-offset-1 ring-current' : 'opacity-60'}`}>
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="label text-xs">ملاحظة المراجعة</label>
          <textarea rows={2} className="input-field resize-none text-sm"
            placeholder="اختياري — تفاصيل القرار..."
            value={note} onChange={e => setNote(e.target.value)} />
        </div>

        <div className="flex gap-2">
          <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
          <button onClick={handleReview} disabled={saving}
            className="btn-primary text-sm flex-1 disabled:opacity-50">
            {saving ? 'جارٍ...' : 'تأكيد القرار'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Abuse Flags Tab ───────────────────────────────────────────────────────────

function AbuseFlagsTab() {
  const qc = useQueryClient()
  const [filters, setFilters]     = useState({ status: 'open', severity: '' })
  const [reviewing, setReviewing] = useState(null)
  const [scanning, setScanning]   = useState(false)

  const { data: summary } = useQuery({
    queryKey: ['flag-summary'],
    queryFn:  () => auditApi.flagSummary().then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: flags = [], isLoading } = useQuery({
    queryKey: ['abuse-flags', filters],
    queryFn:  () => auditApi.flags({
      status:   filters.status   || undefined,
      severity: filters.severity || undefined,
      page_size: 100,
    }).then(r => r.data.results || r.data),
    refetchInterval: 60_000,
  })

  async function runScan() {
    setScanning(true)
    try {
      const { data } = await auditApi.runDetection(24)
      alert(`تم الفحص — ${data.total} إشارة جديدة`)
      qc.invalidateQueries(['abuse-flags'])
      qc.invalidateQueries(['flag-summary'])
    } catch { } finally { setScanning(false) }
  }

  return (
    <div>
      {/* Summary KPIs */}
      {summary && summary.open_flags?.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          {[
            { label: 'إلغاءات متكررة',   type: 'frequent_cancellations',  color: '#ef4444' },
            { label: 'تعديلات متكررة',   type: 'frequent_edits',           color: '#f59e0b' },
            { label: 'عدم تطابق ERP',    type: 'erp_mismatch',             color: '#8b5cf6' },
            { label: 'نشاط خارج الدوام', type: 'after_hours_activity',     color: '#3b82f6' },
          ].map(k => {
            const count = summary.open_flags
              .filter(f => f.flag_type === k.type)
              .reduce((s, f) => s + f.count, 0)
            if (!count) return null
            return (
              <div key={k.type} className="bg-white border border-gray-100 rounded-xl px-4 py-3">
                <div className="text-xs text-gray-400">{k.label}</div>
                <div className="text-2xl font-black" style={{ color: k.color }}>{count}</div>
              </div>
            )
          })}
        </div>
      )}

      {/* Filters + scan */}
      <div className="flex gap-3 mb-4 flex-wrap items-end">
        <div className="flex gap-1">
          {[
            { v: 'open',     label: 'مفتوح' },
            { v: 'reviewed', label: 'مراجع' },
            { v: '',         label: 'الكل' },
          ].map(f => (
            <button key={f.v}
              onClick={() => setFilters(p => ({ ...p, status: f.v }))}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                filters.status === f.v
                  ? 'bg-brand-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}>
              {f.label}
            </button>
          ))}
        </div>
        <select className="input-field w-36 text-sm" value={filters.severity}
          onChange={e => setFilters(p => ({ ...p, severity: e.target.value }))}>
          <option value="">كل الخطورة</option>
          <option value="critical">حرج</option>
          <option value="warning">تحذير</option>
          <option value="info">معلومة</option>
        </select>
        <div className="flex-1" />
        <button onClick={runScan} disabled={scanning}
          className="btn-secondary text-sm disabled:opacity-50">
          {scanning ? '🔍 جارٍ الفحص...' : '🔍 فحص الآن'}
        </button>
      </div>

      {/* Flags list */}
      {isLoading ? (
        <div className="space-y-2 animate-pulse">
          {[1,2,3].map(i => <div key={i} className="h-20 bg-gray-100 rounded-xl" />)}
        </div>
      ) : flags.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <div className="text-4xl mb-2">✅</div>
          <div className="font-semibold">
            {filters.status === 'open' ? 'لا توجد إشارات مفتوحة' : 'لا توجد إشارات'}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {flags.map(flag => {
            const s  = SEVERITY_CFG[flag.severity]  || SEVERITY_CFG.warning
            const st = FLAG_STATUS_CFG[flag.status] || FLAG_STATUS_CFG.open
            return (
              <div key={flag.id}
                className="bg-white border border-gray-100 rounded-xl p-4 hover:border-gray-200 transition-colors">
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-full flex items-center justify-center text-lg shrink-0"
                    style={{ background: s.bg }}>
                    ⚠️
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="font-bold text-gray-800 text-sm">
                        {flag.flag_label || flag.flag_type}
                      </span>
                      <span className="badge text-xs px-2 py-0.5"
                        style={{ background: s.bg, color: s.text }}>
                        <span className="w-1.5 h-1.5 rounded-full inline-block ml-1"
                          style={{ background: s.dot }} />
                        {s.label}
                      </span>
                      <span className="badge text-xs px-2 py-0.5"
                        style={{ background: st.bg, color: st.text }}>
                        {st.label}
                      </span>
                    </div>

                    <div className="text-sm text-gray-600 leading-relaxed">
                      {flag.description}
                    </div>

                    <div className="flex items-center gap-3 mt-2 text-xs text-gray-400 flex-wrap">
                      <span>👤 {flag.staff_name}</span>
                      {flag.staff_branch && <span>🏥 {flag.staff_branch}</span>}
                      <span>📊 {flag.count} حدث</span>
                      <span>🕒 {timeAgo(flag.detected_at)}</span>
                    </div>

                    {flag.review_note && (
                      <div className="mt-2 text-xs text-gray-500 bg-gray-50 rounded-lg px-2 py-1">
                        ملاحظة المراجعة: {flag.review_note}
                      </div>
                    )}
                  </div>

                  {flag.status === 'open' && (
                    <button
                      onClick={() => setReviewing(flag)}
                      className="btn-secondary text-xs px-3 py-1.5 shrink-0">
                      مراجعة
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {reviewing && (
        <ReviewModal
          flag={reviewing}
          onClose={() => setReviewing(null)}
          onSaved={() => setReviewing(null)}
        />
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AuditPage() {
  const [tab, setTab] = useState('flags')

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-4">
            <div>
              <h1 className="text-lg font-black text-gray-900">سجلات المراجعة والمراقبة</h1>
              <p className="text-xs text-gray-400 mt-0.5">
                تتبع كل إجراء · كشف الأنماط المشبوهة · حماية العمليات
              </p>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-0 mt-3 border-b border-gray-200 -mb-px overflow-x-auto">
            <button
              onClick={() => setTab('flags')}
              className={`px-5 py-3 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap ${
                tab === 'flags'
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              ⚠️ الإشارات المشبوهة
            </button>
            <button
              onClick={() => setTab('logs')}
              className={`px-5 py-3 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap ${
                tab === 'logs'
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              📋 سجل الإجراءات
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-6 py-5">
        {tab === 'flags' && <AbuseFlagsTab />}
        {tab === 'logs'  && <AuditLogsTab />}
      </div>
    </div>
  )
}
