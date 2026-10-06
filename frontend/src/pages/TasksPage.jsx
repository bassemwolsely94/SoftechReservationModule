/**
 * TasksPage.jsx
 * Main task management page — List, Kanban, and My Tasks views.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { tasksApi, branchesApi, usersApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── Constants ──────────────────────────────────────────────────────────────────

const STATUS_LABELS = {
  open:        { label: 'مفتوحة',      color: 'bg-blue-100 text-blue-700',    dot: 'bg-blue-500'   },
  in_progress: { label: 'قيد التنفيذ', color: 'bg-yellow-100 text-yellow-700',dot: 'bg-yellow-500' },
  on_hold:     { label: 'متوقفة',      color: 'bg-gray-100 text-gray-600',    dot: 'bg-gray-400'   },
  completed:   { label: 'مكتملة',      color: 'bg-green-100 text-green-700',  dot: 'bg-green-500'  },
  cancelled:   { label: 'ملغاة',       color: 'bg-red-100 text-red-500',      dot: 'bg-red-400'    },
}

const PRIORITY_LABELS = {
  low:      { label: 'منخفضة',  color: 'text-gray-400',  bg: 'bg-gray-50'   },
  normal:   { label: 'عادية',   color: 'text-blue-500',  bg: 'bg-blue-50'   },
  high:     { label: 'عالية',   color: 'text-orange-500',bg: 'bg-orange-50' },
  urgent:   { label: 'عاجلة',   color: 'text-red-500',   bg: 'bg-red-50'    },
  critical: { label: 'حرجة',    color: 'text-red-700',   bg: 'bg-red-100'   },
}

const TYPE_LABELS = {
  stock_count: 'جرد', receiving: 'استلام', transfer: 'تحويل',
  delivery: 'توصيل', shortage: 'نقص', purchasing: 'مشتريات',
  maintenance: 'صيانة', meeting: 'اجتماع', training: 'تدريب',
  audit: 'تدقيق', customer: 'عملاء', other: 'أخرى',
}

const KANBAN_COLS = [
  { key: 'open',        label: 'مفتوحة',       headerClass: 'bg-blue-50   border-blue-200' },
  { key: 'in_progress', label: 'قيد التنفيذ',  headerClass: 'bg-yellow-50 border-yellow-200' },
  { key: 'on_hold',     label: 'متوقفة',       headerClass: 'bg-gray-50   border-gray-200' },
  { key: 'completed',   label: 'مكتملة',       headerClass: 'bg-green-50  border-green-200' },
]

// ── Small helpers ──────────────────────────────────────────────────────────────

function fmt(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtRelative(d) {
  if (!d) return null
  const diff = new Date(d) - new Date()
  const days = Math.round(diff / 86400000)
  if (days < 0) return { label: `متأخر ${Math.abs(days)} يوم`, cls: 'text-red-600 font-semibold' }
  if (days === 0) return { label: 'اليوم', cls: 'text-orange-600 font-semibold' }
  if (days === 1) return { label: 'غداً', cls: 'text-orange-500' }
  if (days <= 7) return { label: `${days} أيام`, cls: 'text-yellow-600' }
  return { label: fmt(d), cls: 'text-gray-500' }
}

// ── PriorityBadge ─────────────────────────────────────────────────────────────

function PriorityBadge({ priority }) {
  const p = PRIORITY_LABELS[priority] || PRIORITY_LABELS.normal
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-1.5 py-0.5 rounded ${p.bg} ${p.color}`}>
      {priority === 'critical' && '🔴'}
      {priority === 'urgent' && '🟠'}
      {p.label}
    </span>
  )
}

function StatusBadge({ status }) {
  const s = STATUS_LABELS[status] || STATUS_LABELS.open
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${s.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}

// ── TaskCard (Kanban) ─────────────────────────────────────────────────────────

function TaskCard({ task, onClick }) {
  const due = fmtRelative(task.due_date)
  return (
    <div
      onClick={() => onClick(task.id)}
      className="bg-white rounded-lg border border-gray-200 p-3 cursor-pointer hover:shadow-md hover:border-brand-300 transition-all group"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-xs text-gray-400 font-mono">{task.task_number}</span>
        <PriorityBadge priority={task.priority} />
      </div>
      <p className="text-sm font-medium text-gray-800 leading-tight mb-2 line-clamp-2 text-right">
        {task.title}
      </p>
      <div className="flex flex-wrap gap-1 mb-2">
        {task.task_type && (
          <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
            {TYPE_LABELS[task.task_type] || task.task_type}
          </span>
        )}
        {task.branch_name && (
          <span className="text-xs bg-brand-50 text-brand-600 px-1.5 py-0.5 rounded">
            {task.branch_name}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400 truncate max-w-[100px]">
          {task.assigned_to_name || 'غير معيَّن'}
        </span>
        {due && <span className={due.cls}>{due.label}</span>}
      </div>
      {(task.subtask_count > 0 || task.item_count > 0) && (
        <div className="flex gap-2 mt-2 pt-2 border-t border-gray-100 text-xs text-gray-400">
          {task.subtask_count > 0 && <span>📋 {task.subtask_count} مهام فرعية</span>}
          {task.item_count > 0 && <span>📦 {task.item_count} عناصر</span>}
        </div>
      )}
      {task.is_overdue && (
        <div className="mt-1 text-xs text-red-500 font-medium">⚠ متأخرة</div>
      )}
    </div>
  )
}

// ── TaskRow (List) ─────────────────────────────────────────────────────────────

function TaskRow({ task, onClick }) {
  const due = fmtRelative(task.due_date)
  return (
    <tr
      onClick={() => onClick(task.id)}
      className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer transition-colors"
    >
      <td className="px-3 py-2.5 text-xs font-mono text-gray-400 whitespace-nowrap">{task.task_number}</td>
      <td className="px-3 py-2.5 text-sm font-medium text-gray-800 max-w-[320px]">
        <div className="truncate text-right">{task.title}</div>
        {task.tags && (
          <div className="flex flex-wrap gap-1 mt-0.5">
            {task.tags.split(',').filter(Boolean).map(t => (
              <span key={t} className="text-xs bg-gray-100 text-gray-400 px-1 rounded">{t.trim()}</span>
            ))}
          </div>
        )}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap"><StatusBadge status={task.status} /></td>
      <td className="px-3 py-2.5 whitespace-nowrap"><PriorityBadge priority={task.priority} /></td>
      <td className="px-3 py-2.5 text-xs text-gray-500 whitespace-nowrap text-right">
        {TYPE_LABELS[task.task_type] || task.task_type}
      </td>
      <td className="px-3 py-2.5 text-xs text-gray-500 whitespace-nowrap text-right">{task.branch_name || '—'}</td>
      <td className="px-3 py-2.5 text-xs text-gray-500 whitespace-nowrap text-right">{task.assigned_to_name || '—'}</td>
      <td className="px-3 py-2.5 text-xs whitespace-nowrap text-right">
        {due ? <span className={due.cls}>{due.label}</span> : <span className="text-gray-400">—</span>}
      </td>
    </tr>
  )
}

// ── New Task Modal ─────────────────────────────────────────────────────────────

function NewTaskModal({ onClose, onCreated, branches, staff }) {
  const [form, setForm] = useState({
    title: '', description: '', task_type: 'other', category: 'operations',
    priority: 'normal', branch: '', assigned_to: '', due_date: '', tags: '',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const submit = async () => {
    if (!form.title.trim()) { setError('العنوان مطلوب.'); return }
    setLoading(true); setError(null)
    try {
      const payload = { ...form }
      if (!payload.branch) delete payload.branch
      if (!payload.assigned_to) delete payload.assigned_to
      if (!payload.due_date) delete payload.due_date
      const { data } = await tasksApi.create(payload)
      onCreated(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'حدث خطأ')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-bold text-gray-800">مهمة جديدة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>
        <div className="p-4 space-y-3">
          {error && <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{error}</div>}

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1 text-right">العنوان *</label>
            <input
              className="w-full border rounded-lg px-3 py-2 text-sm text-right focus:ring-2 focus:ring-brand-400 focus:outline-none"
              placeholder="عنوان المهمة..."
              value={form.title}
              onChange={e => set('title', e.target.value)}
              autoFocus
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1 text-right">النوع</label>
              <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.task_type} onChange={e => set('task_type', e.target.value)}>
                {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الأولوية</label>
              <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.priority} onChange={e => set('priority', e.target.value)}>
                {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الفرع</label>
              <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.branch} onChange={e => set('branch', e.target.value)}>
                <option value="">— جميع الفروع —</option>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الموعد النهائي</label>
              <input
                type="date"
                className="w-full border rounded-lg px-3 py-2 text-sm text-right"
                value={form.due_date}
                onChange={e => set('due_date', e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1 text-right">تعيين إلى</label>
            <select className="w-full border rounded-lg px-3 py-2 text-sm text-right" value={form.assigned_to} onChange={e => set('assigned_to', e.target.value)}>
              <option value="">— اختر موظف —</option>
              {staff.map(s => <option key={s.id} value={s.id}>{s.full_name || s.username}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1 text-right">الوصف</label>
            <textarea
              className="w-full border rounded-lg px-3 py-2 text-sm text-right resize-none"
              rows={3} placeholder="تفاصيل اختيارية..."
              value={form.description}
              onChange={e => set('description', e.target.value)}
            />
          </div>
        </div>
        <div className="flex gap-2 p-4 border-t justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
          <button
            onClick={submit}
            disabled={loading}
            className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium"
          >
            {loading ? 'جاري الحفظ...' : 'إنشاء المهمة'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TasksPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuthStore()

  const [view, setView] = useState('list') // list | kanban | mine
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)
  const [branches, setBranches] = useState([])
  const [staff, setStaff] = useState([])
  const [showNewModal, setShowNewModal] = useState(false)

  // Filters
  const [filters, setFilters] = useState({
    status: searchParams.get('status') || '',
    priority: '',
    task_type: '',
    branch: '',
    search: '',
    overdue: '',
  })

  const setFilter = (k, v) => setFilters(f => ({ ...f, [k]: v }))

  // Load reference data
  useEffect(() => {
    branchesApi.list().then(r => setBranches(r.data || [])).catch(() => {})
    usersApi.list().then(r => setStaff(r.data?.results || r.data || [])).catch(() => {})
  }, [])

  // Load tasks
  const loadTasks = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      Object.entries(filters).forEach(([k, v]) => { if (v) params[k] = v })
      if (view === 'mine') params.mine = '1'

      const { data } = await tasksApi.list(params)
      setTasks(data.results || data || [])
    } catch {
      setTasks([])
    } finally {
      setLoading(false)
    }
  }, [filters, view])

  useEffect(() => { loadTasks() }, [loadTasks])

  const openTask = (id) => navigate(`/tasks/${id}`)

  // Kanban grouping
  const kanbanGroups = useMemo(() => {
    const groups = {}
    KANBAN_COLS.forEach(c => { groups[c.key] = [] })
    tasks.forEach(t => {
      if (groups[t.status]) groups[t.status].push(t)
      // show cancelled separately? skip for now
    })
    return groups
  }, [tasks])

  const handleCreated = (task) => {
    setShowNewModal(false)
    navigate(`/tasks/${task.id}`)
  }

  // Summary counts
  const counts = useMemo(() => {
    const c = { total: tasks.length, overdue: 0, urgent: 0, open: 0 }
    tasks.forEach(t => {
      if (t.is_overdue) c.overdue++
      if (t.priority === 'urgent' || t.priority === 'critical') c.urgent++
      if (t.status === 'open' || t.status === 'in_progress') c.open++
    })
    return c
  }, [tasks])

  return (
    <div className="h-full flex flex-col bg-gray-50" dir="rtl">

      {/* ── Header ── */}
      <div className="bg-white border-b px-6 py-4 flex-shrink-0">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold text-gray-800">إدارة المهام التشغيلية</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {counts.total} مهمة
              {counts.open > 0 && <> · <span className="text-blue-600">{counts.open} نشطة</span></>}
              {counts.overdue > 0 && <> · <span className="text-red-600">{counts.overdue} متأخرة</span></>}
              {counts.urgent > 0 && <> · <span className="text-orange-600">{counts.urgent} عاجلة</span></>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* View switch */}
            <div className="flex rounded-lg overflow-hidden border border-gray-200">
              {[
                { key: 'list',   label: '≡ قائمة' },
                { key: 'kanban', label: '⊟ كانبان' },
                { key: 'mine',   label: '👤 مهامي' },
              ].map(v => (
                <button
                  key={v.key}
                  onClick={() => setView(v.key)}
                  className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                    view === v.key
                      ? 'bg-brand-600 text-white'
                      : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {v.label}
                </button>
              ))}
            </div>

            <button
              onClick={() => navigate('/tasks/dashboard')}
              className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50"
            >
              📊 لوحة التحكم
            </button>

            <button
              onClick={() => setShowNewModal(true)}
              className="px-4 py-1.5 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 font-medium"
            >
              + مهمة جديدة
            </button>
          </div>
        </div>
      </div>

      {/* ── Filters bar ── */}
      <div className="bg-white border-b px-6 py-2 flex-shrink-0 flex flex-wrap items-center gap-3">
        <input
          className="border rounded-lg px-3 py-1.5 text-sm text-right w-48 focus:ring-2 focus:ring-brand-300 focus:outline-none"
          placeholder="بحث..."
          value={filters.search}
          onChange={e => setFilter('search', e.target.value)}
        />
        <select className="border rounded-lg px-3 py-1.5 text-sm text-right" value={filters.status} onChange={e => setFilter('status', e.target.value)}>
          <option value="">كل الحالات</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select className="border rounded-lg px-3 py-1.5 text-sm text-right" value={filters.priority} onChange={e => setFilter('priority', e.target.value)}>
          <option value="">كل الأولويات</option>
          {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select className="border rounded-lg px-3 py-1.5 text-sm text-right" value={filters.task_type} onChange={e => setFilter('task_type', e.target.value)}>
          <option value="">كل الأنواع</option>
          {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className="border rounded-lg px-3 py-1.5 text-sm text-right" value={filters.branch} onChange={e => setFilter('branch', e.target.value)}>
          <option value="">كل الفروع</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-red-600 cursor-pointer">
          <input type="checkbox" checked={filters.overdue === '1'} onChange={e => setFilter('overdue', e.target.checked ? '1' : '')} />
          متأخرة فقط
        </label>
        {Object.values(filters).some(Boolean) && (
          <button
            onClick={() => setFilters({ status:'',priority:'',task_type:'',branch:'',search:'',overdue:'' })}
            className="text-xs text-gray-400 hover:text-gray-600 underline"
          >
            مسح الفلاتر
          </button>
        )}
      </div>

      {/* ── Content ── */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center justify-center h-48 text-gray-400">
            <div className="text-center">
              <div className="text-2xl mb-2 animate-spin">⟳</div>
              <div className="text-sm">جاري التحميل...</div>
            </div>
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-gray-400">
            <div className="text-4xl mb-3">📋</div>
            <p className="text-sm">لا توجد مهام</p>
            <button
              onClick={() => setShowNewModal(true)}
              className="mt-3 text-sm text-brand-600 underline"
            >
              إنشاء أول مهمة
            </button>
          </div>
        ) : view === 'kanban' ? (
          /* ── Kanban view ── */
          <div className="flex gap-4 p-4 h-full overflow-x-auto">
            {KANBAN_COLS.map(col => (
              <div key={col.key} className="flex-shrink-0 w-72">
                <div className={`flex items-center justify-between px-3 py-2 rounded-t-lg border ${col.headerClass}`}>
                  <span className="text-sm font-semibold text-gray-700">{col.label}</span>
                  <span className="text-xs bg-white text-gray-500 px-2 py-0.5 rounded-full font-medium">
                    {kanbanGroups[col.key]?.length || 0}
                  </span>
                </div>
                <div className="bg-gray-100 rounded-b-lg p-2 space-y-2 min-h-[200px] max-h-[calc(100vh-260px)] overflow-y-auto">
                  {(kanbanGroups[col.key] || []).map(task => (
                    <TaskCard key={task.id} task={task} onClick={openTask} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          /* ── List view ── */
          <div className="p-4">
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-right">
                  <thead>
                    <tr className="bg-gray-50 border-b text-xs text-gray-500 font-semibold">
                      <th className="px-3 py-2.5">الرقم</th>
                      <th className="px-3 py-2.5">العنوان</th>
                      <th className="px-3 py-2.5">الحالة</th>
                      <th className="px-3 py-2.5">الأولوية</th>
                      <th className="px-3 py-2.5">النوع</th>
                      <th className="px-3 py-2.5">الفرع</th>
                      <th className="px-3 py-2.5">المُعيَّن إليه</th>
                      <th className="px-3 py-2.5">الموعد</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tasks.map(t => (
                      <TaskRow key={t.id} task={t} onClick={openTask} />
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── New Task Modal ── */}
      {showNewModal && (
        <NewTaskModal
          onClose={() => setShowNewModal(false)}
          onCreated={handleCreated}
          branches={branches}
          staff={staff}
        />
      )}
    </div>
  )
}
