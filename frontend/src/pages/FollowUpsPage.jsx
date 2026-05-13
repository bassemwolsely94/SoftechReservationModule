/**
 * FollowUpsPage.jsx  —  /followups
 * Chronic medication follow-up task list
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { followupsApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

const STATUS_CFG = {
  pending:     { label: 'معلق',               bg: '#fffbeb', text: '#92400e', dot: '#f59e0b' },
  called:      { label: 'تم الاتصال',         bg: '#eff6ff', text: '#1e40af', dot: '#3b82f6' },
  done:        { label: 'مكتمل',               bg: '#f0fdf4', text: '#166534', dot: '#10b981' },
  missed:      { label: 'فائت',                bg: '#fef2f2', text: '#991b1b', dot: '#ef4444' },
  auto_closed: { label: 'أُغلق تلقائياً',     bg: '#f5f3ff', text: '#5b21b6', dot: '#8b5cf6' },
  cancelled:   { label: 'ملغي',                bg: '#f9fafb', text: '#9ca3af', dot: '#9ca3af' },
}

function StatusBadge({ status }) {
  const s = STATUS_CFG[status] || STATUS_CFG.pending
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold"
      style={{ background: s.bg, color: s.text }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.dot }} />
      {s.label}
    </span>
  )
}

function ActionModal({ task, onClose, onDone }) {
  const [note, setNote] = useState('')
  const [action, setAction] = useState('call')
  const [saving, setSaving] = useState(false)

  async function submit() {
    setSaving(true)
    try {
      if (action === 'call')   await followupsApi.call(task.id, note)
      if (action === 'done')   await followupsApi.done(task.id, note)
      if (action === 'missed') await followupsApi.missed(task.id, note)
      onDone()
    } catch { } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-gray-900">تسجيل نتيجة المتابعة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        <div className="bg-gray-50 rounded-xl p-3 text-sm">
          <div className="font-semibold text-gray-800">{task.customer_name || task.notes?.split(' ')[0]}</div>
          <div className="text-gray-500 font-mono" dir="ltr">{task.customer_phone}</div>
          <div className="text-brand-600 mt-1">💊 {task.item_name}</div>
        </div>
        {task.whatsapp_url && (
          <a href={task.whatsapp_url} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-2 text-sm text-green-700 bg-green-50
              border border-green-200 rounded-xl px-3 py-2 hover:bg-green-100">
            💬 فتح واتساب
          </a>
        )}
        <div className="grid grid-cols-3 gap-2">
          {[
            { v: 'call',   label: '📞 اتصلت',    cls: 'bg-blue-50 text-blue-700 border-blue-200' },
            { v: 'done',   label: '✅ تم الشراء', cls: 'bg-green-50 text-green-700 border-green-200' },
            { v: 'missed', label: '❌ لا رد',      cls: 'bg-red-50 text-red-700 border-red-200' },
          ].map(opt => (
            <button key={opt.v}
              onClick={() => setAction(opt.v)}
              className={`border rounded-xl py-2.5 text-xs font-bold transition-all ${opt.cls}
                ${action === opt.v ? 'ring-2 ring-offset-1 ring-current scale-105' : 'opacity-70'}`}>
              {opt.label}
            </button>
          ))}
        </div>
        <div>
          <label className="label text-xs">ملاحظة</label>
          <textarea rows={2} className="input-field resize-none text-sm"
            placeholder="ملاحظة اختيارية..."
            value={note} onChange={e => setNote(e.target.value)} />
        </div>
        <div className="flex gap-2">
          <button onClick={submit} disabled={saving}
            className="btn-primary flex-1 text-sm disabled:opacity-50">
            {saving ? 'جارٍ...' : 'تسجيل'}
          </button>
          <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
        </div>
      </div>
    </div>
  )
}

export default function FollowUpsPage() {
  const { user } = useAuthStore()
  const qc       = useQueryClient()
  const [activeTask, setActiveTask]   = useState(null)
  const [filters, setFilters]         = useState({ status: 'pending', branch: '' })

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn:  () => branchesApi.list().then(r => r.data.results || r.data),
  })

  const { data: stats } = useQuery({
    queryKey: ['followup-dashboard'],
    queryFn:  () => followupsApi.dashboard().then(r => r.data),
    refetchInterval: 60_000,
  })

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['followup-tasks', filters],
    queryFn:  () => followupsApi.list({
      status: filters.status || undefined,
      branch: filters.branch || undefined,
    }).then(r => r.data.results || r.data),
    refetchInterval: 60_000,
  })

  const invalidate = () => {
    qc.invalidateQueries(['followup-tasks'])
    qc.invalidateQueries(['followup-dashboard'])
    setActiveTask(null)
  }

  const TAB_STATUSES = [
    { v: '',          label: 'الكل' },
    { v: 'pending',   label: `معلق (${stats?.pending || 0})` },
    { v: 'called',    label: `تم الاتصال (${stats?.called || 0})` },
    { v: 'done',      label: 'مكتمل' },
    { v: 'missed',    label: 'فائت' },
    { v: 'auto_closed', label: 'مُغلق تلقائياً' },
  ]

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-4 flex-wrap">
            <div>
              <h1 className="text-lg font-black text-gray-900">متابعة الأدوية المزمنة</h1>
              <p className="text-xs text-gray-400 mt-0.5">
                {stats?.due_today > 0 && (
                  <span className="text-red-600 font-bold ml-2">⚠ {stats.due_today} مستحق اليوم</span>
                )}
                {stats?.overdue > 0 && (
                  <span className="text-red-600 font-bold ml-2">· {stats.overdue} متأخر</span>
                )}
                {stats?.chronic_profiles} بروفايل مزمن
              </p>
            </div>
            <div className="flex-1" />
            {user?.role === 'admin' && (
              <button
                onClick={async () => {
                  await followupsApi.generate({ dry_run: false })
                  qc.invalidateQueries(['followup-tasks'])
                }}
                className="btn-secondary text-sm">
                🔄 تحديث المهام
              </button>
            )}
          </div>

          {/* KPI strip */}
          {stats && (
            <div className="flex gap-3 mt-3 overflow-x-auto">
              {[
                { label: 'معلق',       val: stats.pending,    color: '#f59e0b' },
                { label: 'اتصلت',      val: stats.called,     color: '#3b82f6' },
                { label: 'مستحق اليوم', val: stats.due_today, color: '#ef4444' },
                { label: 'مكتمل',      val: stats.done,       color: '#10b981' },
                { label: 'أُغلق آلياً', val: stats.auto_closed, color: '#8b5cf6' },
              ].map(k => (
                <div key={k.label}
                  className="flex-shrink-0 bg-white border border-gray-200 rounded-xl px-4 py-2">
                  <div className="text-xs text-gray-500">{k.label}</div>
                  <div className="text-xl font-black" style={{ color: k.color }}>{k.val ?? 0}</div>
                </div>
              ))}
            </div>
          )}

          {/* Tab strip */}
          <div className="flex gap-1 mt-3 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
            {TAB_STATUSES.map(t => (
              <button key={t.v}
                onClick={() => setFilters(p => ({ ...p, status: t.v }))}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-colors ${
                  filters.status === t.v
                    ? 'bg-brand-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}>
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* List */}
      <div className="max-w-6xl mx-auto px-6 py-5">
        {isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[1,2,3,4,5].map(i => <div key={i} className="h-20 bg-gray-100 rounded-xl" />)}
          </div>
        ) : tasks.length === 0 ? (
          <div className="card text-center py-12">
            <div className="text-4xl mb-3">💊</div>
            <div className="text-gray-500 font-semibold">لا توجد مهام متابعة</div>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map(task => {
              const isOverdue  = task.is_overdue
              const isPending  = task.status === 'pending'
              return (
                <div key={task.id}
                  className={`bg-white border rounded-xl px-4 py-3 flex items-center gap-4 ${
                    isOverdue && isPending
                      ? 'border-red-200 bg-red-50'
                      : 'border-gray-100 hover:border-brand-200'
                  }`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-gray-800 text-sm">
                        {task.customer_name || '—'}
                      </span>
                      {task.customer_phone && (
                        <span className="text-xs text-gray-400 font-mono" dir="ltr">
                          {task.customer_phone}
                        </span>
                      )}
                      <StatusBadge status={task.status} />
                      {isOverdue && isPending && (
                        <span className="badge bg-red-100 text-red-700 text-xs">⚠ متأخر</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 mt-1 flex-wrap">
                      <span className="text-xs text-brand-600">💊 {task.item_name}</span>
                      <span className="text-xs text-gray-400">{task.branch_name}</span>
                      <span className="text-xs text-gray-400">
                        استحقاق: {task.due_date}
                        {task.source_sale_date && ` · آخر صرف: ${task.source_sale_date}`}
                      </span>
                      {task.attempts > 0 && (
                        <span className="text-xs text-orange-600">
                          {task.attempts} محاولة
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {task.whatsapp_url && (
                      <a href={task.whatsapp_url} target="_blank" rel="noopener noreferrer"
                        className="text-green-600 hover:text-green-800 text-lg p-1"
                        onClick={e => e.stopPropagation()}>
                        💬
                      </a>
                    )}
                    {['pending', 'called'].includes(task.status) && (
                      <button
                        onClick={() => setActiveTask(task)}
                        className="btn-primary text-xs px-3 py-1.5">
                        تسجيل النتيجة
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {activeTask && (
        <ActionModal
          task={activeTask}
          onClose={() => setActiveTask(null)}
          onDone={invalidate}
        />
      )}
    </div>
  )
}
