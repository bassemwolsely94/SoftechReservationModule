/**
 * TaskDashboardPage.jsx
 * Management overview dashboard for pharmacy operations tasks.
 * Shows status distribution, overdue counts, completion rate, by-branch, upcoming tasks.
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { tasksApi, branchesApi } from '../api/client'

// ── Helpers ────────────────────────────────────────────────────────────────────

const STATUS_LABELS = {
  open:        { label: 'مفتوحة',      color: 'text-blue-600',   bg: 'bg-blue-50',    bar: 'bg-blue-500'    },
  in_progress: { label: 'قيد التنفيذ', color: 'text-yellow-600', bg: 'bg-yellow-50',  bar: 'bg-yellow-500'  },
  on_hold:     { label: 'متوقفة',      color: 'text-gray-500',   bg: 'bg-gray-50',    bar: 'bg-gray-400'    },
  completed:   { label: 'مكتملة',      color: 'text-green-600',  bg: 'bg-green-50',   bar: 'bg-green-500'   },
  cancelled:   { label: 'ملغاة',       color: 'text-red-500',    bg: 'bg-red-50',     bar: 'bg-red-400'     },
}

const PRIORITY_LABELS = {
  critical: { label: 'حرجة',    color: 'text-red-700',    bg: 'bg-red-100'   },
  urgent:   { label: 'عاجلة',   color: 'text-red-500',    bg: 'bg-red-50'    },
  high:     { label: 'عالية',   color: 'text-orange-500', bg: 'bg-orange-50' },
  normal:   { label: 'عادية',   color: 'text-blue-500',   bg: 'bg-blue-50'   },
  low:      { label: 'منخفضة',  color: 'text-gray-400',   bg: 'bg-gray-50'   },
}

function fmt(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}
function fmtRelDays(d) {
  if (!d) return null
  const diff = new Date(d) - new Date()
  const days = Math.round(diff / 86400000)
  if (days < 0) return { label: `متأخر ${Math.abs(days)} يوم`, cls: 'text-red-600 font-semibold' }
  if (days === 0) return { label: 'اليوم', cls: 'text-orange-600 font-semibold' }
  if (days === 1) return { label: 'غداً', cls: 'text-orange-500' }
  return { label: `${days} أيام`, cls: 'text-gray-500' }
}

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color = 'text-gray-800', bg = 'bg-white', icon, onClick }) {
  return (
    <div
      onClick={onClick}
      className={`rounded-xl border border-gray-200 ${bg} p-4 ${onClick ? 'cursor-pointer hover:shadow-md transition-shadow' : ''}`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-500 mb-1">{label}</p>
          <p className={`text-2xl font-bold ${color}`}>{value ?? '—'}</p>
          {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
        </div>
        {icon && <span className="text-2xl opacity-60">{icon}</span>}
      </div>
    </div>
  )
}

// ── Status bar ────────────────────────────────────────────────────────────────

function StatusBar({ counts, total }) {
  if (!total) return <div className="text-xs text-gray-400 text-center py-2">لا توجد مهام</div>
  return (
    <div className="space-y-2">
      {Object.entries(STATUS_LABELS).map(([key, meta]) => {
        const cnt = counts[key] || 0
        const pct = total ? Math.round(cnt / total * 100) : 0
        return (
          <div key={key} className="flex items-center gap-3">
            <span className={`text-xs w-24 text-right ${meta.color}`}>{meta.label}</span>
            <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full ${meta.bar} rounded-full transition-all`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-gray-500 w-8 text-left">{cnt}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── Upcoming task row ─────────────────────────────────────────────────────────

function UpcomingRow({ task, onClick }) {
  const due = fmtRelDays(task.due_date)
  const p = PRIORITY_LABELS[task.priority] || PRIORITY_LABELS.normal
  return (
    <div
      onClick={() => onClick(task.id)}
      className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 cursor-pointer transition-colors"
    >
      <div className={`w-2 h-8 rounded-full ${STATUS_LABELS[task.status]?.bar || 'bg-gray-300'} flex-shrink-0`} />
      <div className="flex-1 text-right min-w-0">
        <p className="text-sm font-medium text-gray-700 truncate">{task.title}</p>
        <p className="text-xs text-gray-400 truncate">{task.branch_name || 'عام'} · {task.assigned_to_name || 'غير معيَّن'}</p>
      </div>
      <div className="text-right flex-shrink-0">
        <span className={`text-xs ${p.color}`}>{p.label}</span>
        {due && <p className={`text-xs ${due.cls}`}>{due.label}</p>}
      </div>
    </div>
  )
}

// ── Schedules panel ───────────────────────────────────────────────────────────

function SchedulesPanel({ schedules, onRun }) {
  if (!schedules.length) return <p className="text-xs text-gray-400 text-center py-4">لا توجد جداول</p>
  return (
    <div className="space-y-2">
      {schedules.map(s => (
        <div key={s.id} className="flex items-center gap-3 p-2 rounded-lg bg-gray-50">
          <div className="flex-1 text-right">
            <p className="text-sm font-medium text-gray-700">{s.name}</p>
            <p className="text-xs text-gray-400">
              {s.frequency === 'daily' ? 'يومي' : s.frequency === 'weekly' ? 'أسبوعي' : 'شهري'}
              {s.branch_name && ` · ${s.branch_name}`}
            </p>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-xs text-gray-400">
              {s.generated_count} مهمة
            </p>
            <span className={`text-xs ${s.is_active ? 'text-green-600' : 'text-gray-400'}`}>
              {s.is_active ? 'نشط' : 'موقوف'}
            </span>
          </div>
          {s.is_active && (
            <button
              onClick={() => onRun(s.id)}
              className="text-xs text-brand-600 hover:underline px-2"
            >
              تشغيل
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TaskDashboardPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [schedules, setSchedules] = useState([])
  const [branch, setBranch] = useState('')
  const [branches, setBranches] = useState([])

  useEffect(() => {
    branchesApi.list().then(r => setBranches(r.data || [])).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    const params = branch ? { branch } : {}
    Promise.all([
      tasksApi.dashboard(params),
      tasksApi.listSchedules({ active: '1' }),
    ]).then(([dashRes, schRes]) => {
      setData(dashRes.data)
      setSchedules(schRes.data?.results || schRes.data || [])
    }).catch(() => {
      setData(null)
    }).finally(() => setLoading(false))
  }, [branch])

  const runSchedule = async (id) => {
    try {
      await tasksApi.runSchedule(id)
      // Refresh
      tasksApi.dashboard(branch ? { branch } : {}).then(r => setData(r.data))
    } catch {}
  }

  const openFiltered = (status) => navigate(`/tasks?status=${status}`)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400" dir="rtl">
        <div className="text-center">
          <div className="text-3xl mb-2 animate-spin">⟳</div>
          <p className="text-sm">جاري التحميل...</p>
        </div>
      </div>
    )
  }

  const total = data?.total_tasks || 0
  const statusCounts = data?.status_counts || {}
  const priorityCounts = data?.priority_counts || {}
  const activeCount = (statusCounts.open || 0) + (statusCounts.in_progress || 0)

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* ── Header ── */}
      <div className="bg-white border-b px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-800">لوحة تحكم المهام</h1>
          <p className="text-sm text-gray-500 mt-0.5">نظرة عامة على المهام التشغيلية</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="border rounded-lg px-3 py-1.5 text-sm text-right"
            value={branch}
            onChange={e => setBranch(e.target.value)}
          >
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <button
            onClick={() => navigate('/tasks')}
            className="px-4 py-1.5 text-sm border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50"
          >
            ← المهام
          </button>
          <button
            onClick={() => navigate('/tasks/schedules')}
            className="px-4 py-1.5 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700"
          >
            ⏱ إدارة الجداول
          </button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-4 space-y-4">

        {/* ── KPI cards row ── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <KpiCard
            label="إجمالي المهام"
            value={total}
            icon="📋"
            onClick={() => navigate('/tasks')}
          />
          <KpiCard
            label="نشطة"
            value={activeCount}
            sub={`${statusCounts.open || 0} مفتوحة + ${statusCounts.in_progress || 0} تنفيذ`}
            color="text-blue-600"
            bg="bg-blue-50"
            icon="⚡"
            onClick={() => openFiltered('open')}
          />
          <KpiCard
            label="متأخرة"
            value={data?.overdue_count || 0}
            color={(data?.overdue_count || 0) > 0 ? 'text-red-600' : 'text-gray-400'}
            bg={(data?.overdue_count || 0) > 0 ? 'bg-red-50' : 'bg-white'}
            icon="⚠"
            onClick={() => navigate('/tasks?overdue=1')}
          />
          <KpiCard
            label="معدل الإتمام (30 يوم)"
            value={`${data?.completion_rate || 0}%`}
            color="text-green-600"
            bg="bg-green-50"
            icon="✅"
          />
        </div>

        {/* ── Priority alerts row ── */}
        {(priorityCounts.critical > 0 || priorityCounts.urgent > 0) && (
          <div className="flex gap-3 flex-wrap">
            {[['critical', '🔴'], ['urgent', '🟠']].map(([key, emoji]) => (
              priorityCounts[key] > 0 && (
                <button
                  key={key}
                  onClick={() => navigate(`/tasks?priority=${key}`)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium ${PRIORITY_LABELS[key].bg} ${PRIORITY_LABELS[key].color} hover:shadow-sm transition-shadow`}
                >
                  {emoji} {priorityCounts[key]} مهام {PRIORITY_LABELS[key].label}
                </button>
              )
            ))}
          </div>
        )}

        <div className="grid grid-cols-3 gap-4">

          {/* ── Status distribution ── */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="font-semibold text-gray-700 text-sm mb-4 text-right">توزيع الحالات</h3>
            <StatusBar counts={statusCounts} total={total} />
          </div>

          {/* ── By type ── */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="font-semibold text-gray-700 text-sm mb-4 text-right">حسب النوع</h3>
            {data?.type_counts?.length > 0 ? (
              <div className="space-y-2">
                {data.type_counts.slice(0, 8).map(tc => (
                  <div key={tc.type} className="flex items-center gap-2">
                    <span className="text-xs text-gray-500 w-20 text-right truncate">{tc.label}</span>
                    <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-brand-400 rounded-full"
                        style={{ width: `${total ? Math.round(tc.count / total * 100) : 0}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500 w-6 text-left">{tc.count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400 text-center py-4">لا توجد بيانات</p>
            )}
          </div>

          {/* ── By branch ── */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="font-semibold text-gray-700 text-sm mb-4 text-right">حسب الفرع</h3>
            {data?.by_branch?.length > 0 ? (
              <div className="space-y-2">
                {data.by_branch.map((b, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-gray-500 text-right truncate flex-1">{b.branch__name}</span>
                    <div className="flex items-center gap-2 ml-2">
                      <span className="text-blue-500 w-5 text-left">{b.open}</span>
                      <span className="text-gray-700 font-medium w-6 text-left">{b.total}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400 text-center py-4">لا توجد بيانات</p>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">

          {/* ── Upcoming due soon ── */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-gray-700 text-sm">المهام المستحقة قريباً</h3>
              <button onClick={() => navigate('/tasks?overdue=1')} className="text-xs text-brand-600 hover:underline">عرض الكل</button>
            </div>
            {data?.due_soon?.length > 0 ? (
              <div className="space-y-1">
                {data.due_soon.map(t => (
                  <UpcomingRow key={t.id} task={t} onClick={id => navigate(`/tasks/${id}`)} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400 text-center py-6">لا توجد مهام مستحقة هذا الأسبوع</p>
            )}
          </div>

          {/* ── Recent activity ── */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="font-semibold text-gray-700 text-sm">آخر النشاطات</h3>
              <button onClick={() => navigate('/tasks')} className="text-xs text-brand-600 hover:underline">عرض الكل</button>
            </div>
            {data?.recent_tasks?.length > 0 ? (
              <div className="space-y-1">
                {data.recent_tasks.map(t => (
                  <UpcomingRow key={t.id} task={t} onClick={id => navigate(`/tasks/${id}`)} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400 text-center py-6">لا توجد مهام حديثة</p>
            )}
          </div>
        </div>

        {/* ── Schedules ── */}
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-700 text-sm">الجداول التلقائية النشطة</h3>
            <button onClick={() => navigate('/tasks/schedules')} className="text-xs text-brand-600 hover:underline">إدارة الجداول</button>
          </div>
          <SchedulesPanel schedules={schedules.slice(0, 5)} onRun={runSchedule} />
        </div>

      </div>
    </div>
  )
}
