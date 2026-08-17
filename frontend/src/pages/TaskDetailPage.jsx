/**
 * TaskDetailPage.jsx
 * Full task detail — info, chatter, items/checklist, attachments, audit log.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { tasksApi, branchesApi, usersApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── Constants (shared with TasksPage) ─────────────────────────────────────────

const STATUS_LABELS = {
  open:        { label: 'مفتوحة',      color: 'bg-blue-100 text-blue-700' },
  in_progress: { label: 'قيد التنفيذ', color: 'bg-yellow-100 text-yellow-700' },
  on_hold:     { label: 'متوقفة',      color: 'bg-gray-100 text-gray-600' },
  completed:   { label: 'مكتملة',      color: 'bg-green-100 text-green-700' },
  cancelled:   { label: 'ملغاة',       color: 'bg-red-100 text-red-500' },
}

const PRIORITY_LABELS = {
  low: 'منخفضة', normal: 'عادية', high: 'عالية', urgent: 'عاجلة', critical: 'حرجة',
}

const TYPE_LABELS = {
  stock_count: 'جرد', receiving: 'استلام', transfer: 'تحويل',
  delivery: 'توصيل', shortage: 'نقص', purchasing: 'مشتريات',
  maintenance: 'صيانة', meeting: 'اجتماع', training: 'تدريب',
  audit: 'تدقيق', customer: 'عملاء', other: 'أخرى',
}

const AUDIT_ACTION_LABELS = {
  created: 'إنشاء', status_changed: 'تغيير الحالة',
  assigned: 'تعيين', unassigned: 'إلغاء تعيين',
  priority_changed: 'تغيير الأولوية', due_date_changed: 'تغيير الموعد',
  completed: 'اكتمال', comment_added: 'تعليق جديد',
  attachment_added: 'مرفق جديد', field_changed: 'تغيير حقل',
}

function fmt(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}
function fmtTime(d) {
  if (!d) return ''
  return new Date(d).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// ── Section card wrapper ───────────────────────────────────────────────────────

function Section({ title, icon, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-right hover:bg-gray-50"
        onClick={() => setOpen(o => !o)}
      >
        <span className="font-semibold text-gray-700 text-sm flex items-center gap-2">
          {icon} {title}
        </span>
        <span className="text-gray-400 text-sm">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="border-t">{children}</div>}
    </div>
  )
}

// ── Chatter ────────────────────────────────────────────────────────────────────

function Chatter({ taskId, messages, onRefresh }) {
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const text = body.trim()
    if (!text) return
    setSending(true)
    try {
      await tasksApi.sendMessage(taskId, text)
      setBody('')
      onRefresh()
    } catch {
    } finally {
      setSending(false)
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send()
  }

  const visibleMsgs = messages.filter(m => !m.is_deleted)

  return (
    <div className="p-4">
      <div className="space-y-3 max-h-72 overflow-y-auto mb-3">
        {visibleMsgs.length === 0 ? (
          <p className="text-center text-xs text-gray-400 py-4">لا توجد رسائل بعد</p>
        ) : visibleMsgs.map(m => (
          <div key={m.id} className={`flex gap-2 ${m.message_type === 'system' ? 'justify-center' : 'justify-end'}`}>
            {m.message_type === 'system' ? (
              <span className="text-xs text-gray-400 bg-gray-50 px-3 py-1 rounded-full">{m.body}</span>
            ) : (
              <div className="max-w-[75%]">
                <div className="bg-brand-50 border border-brand-100 rounded-xl rounded-tr-sm px-3 py-2">
                  <p className="text-sm text-gray-700 text-right whitespace-pre-line">{m.body}</p>
                </div>
                <p className="text-xs text-gray-400 mt-0.5 text-right">
                  {m.author_name} · {fmtTime(m.created_at)}
                </p>
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2">
        <textarea
          className="flex-1 border rounded-lg px-3 py-2 text-sm text-right resize-none focus:ring-2 focus:ring-brand-300 focus:outline-none"
          rows={2}
          placeholder="اكتب تعليقاً... (Ctrl+Enter للإرسال)"
          value={body}
          onChange={e => setBody(e.target.value)}
          onKeyDown={handleKey}
        />
        <button
          onClick={send}
          disabled={sending || !body.trim()}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-40 self-end"
        >
          {sending ? '...' : 'إرسال'}
        </button>
      </div>
    </div>
  )
}

// ── Checklist ──────────────────────────────────────────────────────────────────

function Checklist({ taskId, items, onRefresh }) {
  const [newName, setNewName] = useState('')
  const [adding, setAdding] = useState(false)

  const addItem = async () => {
    if (!newName.trim()) return
    setAdding(true)
    try {
      await tasksApi.addItem(taskId, { item_name: newName.trim() })
      setNewName('')
      onRefresh()
    } catch {
    } finally {
      setAdding(false)
    }
  }

  const toggleCheck = async (item) => {
    try {
      await tasksApi.updateItem(taskId, item.id, { is_checked: !item.is_checked })
      onRefresh()
    } catch {}
  }

  const deleteItem = async (item) => {
    try {
      await tasksApi.deleteItem(taskId, item.id)
      onRefresh()
    } catch {}
  }

  const checked = items.filter(i => i.is_checked).length
  const pct = items.length ? Math.round(checked / items.length * 100) : 0

  return (
    <div className="p-4">
      {items.length > 0 && (
        <div className="mb-3">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>{checked} / {items.length}</span>
            <span>{pct}%</span>
          </div>
          <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div className="h-full bg-brand-500 rounded-full transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}
      <div className="space-y-1.5 mb-3 max-h-64 overflow-y-auto">
        {items.map(item => (
          <div key={item.id} className={`flex items-center gap-2 p-2 rounded-lg group ${item.is_checked ? 'bg-green-50' : 'bg-gray-50'}`}>
            <input
              type="checkbox"
              checked={item.is_checked}
              onChange={() => toggleCheck(item)}
              className="w-4 h-4 accent-brand-600 cursor-pointer"
            />
            <div className="flex-1 text-right">
              <p className={`text-sm ${item.is_checked ? 'line-through text-gray-400' : 'text-gray-700'}`}>
                {item.item_name || item.item_code || '—'}
              </p>
              {(item.quantity_expected || item.quantity_actual) && (
                <p className="text-xs text-gray-400">
                  {item.quantity_actual ?? '—'} / {item.quantity_expected ?? '—'} {item.unit}
                </p>
              )}
            </div>
            <button
              onClick={() => deleteItem(item)}
              className="opacity-0 group-hover:opacity-100 text-xs text-red-400 hover:text-red-600"
            >✕</button>
          </div>
        ))}
        {items.length === 0 && (
          <p className="text-center text-xs text-gray-400 py-3">لا توجد عناصر</p>
        )}
      </div>
      <div className="flex gap-2">
        <input
          className="flex-1 border rounded-lg px-3 py-2 text-sm text-right focus:ring-2 focus:ring-brand-300 focus:outline-none"
          placeholder="أضف عنصراً..."
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addItem()}
        />
        <button
          onClick={addItem}
          disabled={adding || !newName.trim()}
          className="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-40"
        >
          {adding ? '...' : 'إضافة'}
        </button>
      </div>
    </div>
  )
}

// ── Attachments ────────────────────────────────────────────────────────────────

function Attachments({ taskId, attachments, onRefresh }) {
  const fileRef = useRef(null)
  const [uploading, setUploading] = useState(false)

  const upload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      await tasksApi.uploadAttachment(taskId, fd)
      onRefresh()
    } catch {
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const remove = async (att) => {
    if (!window.confirm(`حذف "${att.file_name}"؟`)) return
    try {
      await tasksApi.deleteAttachment(taskId, att.id)
      onRefresh()
    } catch {}
  }

  const iconFor = (type) => ({ image: '🖼', pdf: '📄', excel: '📊' }[type] || '📎')

  return (
    <div className="p-4">
      <div className="space-y-2 mb-3">
        {attachments.length === 0 && (
          <p className="text-center text-xs text-gray-400 py-3">لا توجد مرفقات</p>
        )}
        {attachments.map(att => (
          <div key={att.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg group">
            <span className="text-lg">{iconFor(att.file_type)}</span>
            <div className="flex-1 text-right">
              <a href={att.file_url} target="_blank" rel="noreferrer"
                className="text-sm text-brand-600 hover:underline font-medium">{att.file_name}</a>
              <p className="text-xs text-gray-400">
                {att.uploaded_by_name} · {fmtTime(att.uploaded_at)}
                {att.file_size && ` · ${(att.file_size / 1024).toFixed(0)} KB`}
              </p>
            </div>
            <button
              onClick={() => remove(att)}
              className="opacity-0 group-hover:opacity-100 text-xs text-red-400 hover:text-red-600"
            >✕</button>
          </div>
        ))}
      </div>
      <input ref={fileRef} type="file" className="hidden" onChange={upload} />
      <button
        onClick={() => fileRef.current?.click()}
        disabled={uploading}
        className="w-full py-2 text-sm border-2 border-dashed border-gray-200 text-gray-500 rounded-lg hover:border-brand-300 hover:text-brand-600 transition-colors disabled:opacity-40"
      >
        {uploading ? 'جاري الرفع...' : '+ رفع ملف'}
      </button>
    </div>
  )
}

// ── Assignments panel ──────────────────────────────────────────────────────────

function AssignmentsPanel({ taskId, assignments, staff, onRefresh }) {
  const [staffId, setStaffId] = useState('')
  const [role, setRole] = useState('contributor')
  const [adding, setAdding] = useState(false)

  const add = async () => {
    if (!staffId) return
    setAdding(true)
    try {
      await tasksApi.addAssignment(taskId, { staff: staffId, role })
      setStaffId('')
      onRefresh()
    } catch {
    } finally {
      setAdding(false)
    }
  }

  const remove = async (asgId) => {
    try {
      await tasksApi.removeAssignment(taskId, asgId)
      onRefresh()
    } catch {}
  }

  const ROLES = { lead: 'رئيسي', contributor: 'مساهم', reviewer: 'مراجع', observer: 'مراقب' }

  return (
    <div className="p-4">
      <div className="space-y-2 mb-3">
        {assignments.length === 0 && (
          <p className="text-center text-xs text-gray-400 py-2">لا توجد تعيينات إضافية</p>
        )}
        {assignments.map(a => (
          <div key={a.id} className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg group">
            <div className="w-7 h-7 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-xs font-bold">
              {(a.staff_name || '?')[0]}
            </div>
            <div className="flex-1 text-right">
              <p className="text-sm font-medium text-gray-700">{a.staff_name}</p>
              <p className="text-xs text-gray-400">{ROLES[a.role] || a.role}</p>
            </div>
            {a.is_completed && <span className="text-xs text-green-600">✓</span>}
            <button onClick={() => remove(a.id)} className="opacity-0 group-hover:opacity-100 text-xs text-red-400 hover:text-red-600">✕</button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <select
          className="flex-1 border rounded-lg px-2 py-1.5 text-sm text-right"
          value={staffId}
          onChange={e => setStaffId(e.target.value)}
        >
          <option value="">اختر موظفاً...</option>
          {staff.map(s => <option key={s.id} value={s.id}>{s.full_name || s.username}</option>)}
        </select>
        <select className="w-24 border rounded-lg px-2 py-1.5 text-sm text-right" value={role} onChange={e => setRole(e.target.value)}>
          {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <button
          onClick={add}
          disabled={adding || !staffId}
          className="px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-40"
        >
          {adding ? '...' : 'إضافة'}
        </button>
      </div>
    </div>
  )
}

// ── Audit Log panel ────────────────────────────────────────────────────────────

function AuditLogPanel({ logs }) {
  return (
    <div className="p-4 max-h-64 overflow-y-auto">
      {logs.length === 0 ? (
        <p className="text-center text-xs text-gray-400 py-3">لا توجد سجلات</p>
      ) : (
        <div className="space-y-2">
          {logs.map(log => (
            <div key={log.id} className="flex items-start gap-3 text-right">
              <div className="w-2 h-2 rounded-full bg-gray-300 mt-1.5 flex-shrink-0" />
              <div>
                <p className="text-xs text-gray-600">
                  <span className="font-medium">{log.actor_name}</span>
                  {' '}{AUDIT_ACTION_LABELS[log.action] || log.action}
                  {log.old_value && log.new_value && (
                    <> · <span className="text-gray-400 line-through">{log.old_value}</span> → <span className="text-brand-600">{log.new_value}</span></>
                  )}
                </p>
                <p className="text-xs text-gray-400">{fmtTime(log.created_at)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TaskDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuthStore()

  const [task, setTask] = useState(null)
  const [loading, setLoading] = useState(true)
  const [staff, setStaff] = useState([])
  const [branches, setBranches] = useState([])
  const [editMode, setEditMode] = useState(false)
  const [editForm, setEditForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [showComplete, setShowComplete] = useState(false)
  const [completeNotes, setCompleteNotes] = useState('')
  const [completing, setCompleting] = useState(false)

  const loadTask = useCallback(async () => {
    try {
      const { data } = await tasksApi.get(id)
      setTask(data)
    } catch {
      navigate('/tasks')
    } finally {
      setLoading(false)
    }
  }, [id, navigate])

  useEffect(() => {
    loadTask()
    usersApi.list().then(r => setStaff(r.data?.results || r.data || [])).catch(() => {})
    branchesApi.list().then(r => setBranches(r.data || [])).catch(() => {})
  }, [loadTask])

  const startEdit = () => {
    setEditForm({
      title: task.title,
      description: task.description,
      priority: task.priority,
      status: task.status,
      task_type: task.task_type,
      category: task.category,
      assigned_to: task.assigned_to || '',
      branch: task.branch || '',
      due_date: task.due_date ? task.due_date.split('T')[0] : '',
      tags: task.tags,
    })
    setEditMode(true)
  }

  const saveEdit = async () => {
    setSaving(true)
    try {
      const payload = { ...editForm }
      if (!payload.branch) delete payload.branch
      if (!payload.assigned_to) delete payload.assigned_to
      if (!payload.due_date) delete payload.due_date
      await tasksApi.update(id, payload)
      setEditMode(false)
      loadTask()
    } catch {
    } finally {
      setSaving(false)
    }
  }

  const setField = (k, v) => setEditForm(f => ({ ...f, [k]: v }))

  const completeTask = async () => {
    setCompleting(true)
    try {
      await tasksApi.complete(id, { notes: completeNotes })
      setShowComplete(false)
      loadTask()
    } catch {
    } finally {
      setCompleting(false)
    }
  }

  const reopenTask = async () => {
    if (!window.confirm('إعادة فتح هذه المهمة؟')) return
    try {
      await tasksApi.reopen(id)
      loadTask()
    } catch {}
  }

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

  if (!task) return null

  const s = STATUS_LABELS[task.status] || STATUS_LABELS.open
  const isDone = task.status === 'completed' || task.status === 'cancelled'

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* ── Header ── */}
      <div className="bg-white border-b px-6 py-4 sticky top-0 z-10">
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => navigate('/tasks')}
            className="text-gray-400 hover:text-gray-600 text-sm"
          >← المهام</button>
          <span className="text-gray-300">|</span>
          <span className="text-xs font-mono text-gray-400">{task.task_number}</span>
          <span className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full font-medium ${s.color}`}>
            {s.label}
          </span>
          {task.is_overdue && (
            <span className="text-xs text-red-600 font-semibold">⚠ متأخرة</span>
          )}
          <div className="flex-1" />
          {/* Actions */}
          {!isDone && (
            <button
              onClick={() => setShowComplete(true)}
              className="px-4 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium"
            >
              ✓ إغلاق المهمة
            </button>
          )}
          {isDone && (
            <button
              onClick={reopenTask}
              className="px-4 py-1.5 text-sm border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              ↩ إعادة فتح
            </button>
          )}
          {!editMode ? (
            <button
              onClick={startEdit}
              className="px-4 py-1.5 text-sm border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              ✎ تعديل
            </button>
          ) : (
            <>
              <button
                onClick={saveEdit}
                disabled={saving}
                className="px-4 py-1.5 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
              >
                {saving ? '...' : 'حفظ'}
              </button>
              <button
                onClick={() => setEditMode(false)}
                className="px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50 rounded-lg"
              >
                إلغاء
              </button>
            </>
          )}
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-4 grid grid-cols-3 gap-4 items-start">

        {/* ── Left column: main info ── */}
        <div className="col-span-2 space-y-4">

          {/* Title & description */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            {editMode ? (
              <div className="space-y-3">
                <input
                  className="w-full border rounded-lg px-3 py-2 text-base font-bold text-right"
                  value={editForm.title}
                  onChange={e => setField('title', e.target.value)}
                />
                <textarea
                  className="w-full border rounded-lg px-3 py-2 text-sm text-right resize-none"
                  rows={4}
                  value={editForm.description}
                  onChange={e => setField('description', e.target.value)}
                  placeholder="الوصف..."
                />
              </div>
            ) : (
              <>
                <h2 className="text-lg font-bold text-gray-800 text-right mb-2">{task.title}</h2>
                {task.description ? (
                  <p className="text-sm text-gray-600 text-right whitespace-pre-line leading-relaxed">{task.description}</p>
                ) : (
                  <p className="text-sm text-gray-400 text-right italic">لا يوجد وصف</p>
                )}
                {task.tags_list?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-3">
                    {task.tags_list.map(t => (
                      <span key={t} className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{t}</span>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {/* Checklist */}
          <Section title="قائمة الأعمال" icon="✅">
            <Checklist taskId={id} items={task.items || []} onRefresh={loadTask} />
          </Section>

          {/* Chatter */}
          <Section title="التعليقات والنشاط" icon="💬">
            <Chatter taskId={id} messages={task.messages || []} onRefresh={loadTask} />
          </Section>

          {/* Attachments */}
          <Section title="المرفقات" icon="📎" defaultOpen={false}>
            <Attachments taskId={id} attachments={task.attachments || []} onRefresh={loadTask} />
          </Section>

          {/* Audit log */}
          <Section title="سجل الأحداث" icon="📜" defaultOpen={false}>
            <AuditLogPanel logs={task.audit_logs || []} />
          </Section>
        </div>

        {/* ── Right column: metadata ── */}
        <div className="space-y-4">

          {/* Details card */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
            <h3 className="font-semibold text-gray-700 text-sm text-right border-b pb-2">تفاصيل المهمة</h3>

            {editMode ? (
              <div className="space-y-3">
                {[
                  ['الحالة', 'status', Object.entries(STATUS_LABELS).map(([k,v]) => ({ value: k, label: v.label }))],
                  ['الأولوية', 'priority', Object.entries(PRIORITY_LABELS).map(([k,v]) => ({ value: k, label: v }))],
                  ['النوع', 'task_type', Object.entries(TYPE_LABELS).map(([k,v]) => ({ value: k, label: v }))],
                ].map(([label, key, opts]) => (
                  <div key={key}>
                    <label className="block text-xs text-gray-500 mb-1 text-right">{label}</label>
                    <select
                      className="w-full border rounded-lg px-2 py-1.5 text-sm text-right"
                      value={editForm[key]}
                      onChange={e => setField(key, e.target.value)}
                    >
                      {opts.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </div>
                ))}
                <div>
                  <label className="block text-xs text-gray-500 mb-1 text-right">الفرع</label>
                  <select className="w-full border rounded-lg px-2 py-1.5 text-sm text-right" value={editForm.branch} onChange={e => setField('branch', e.target.value)}>
                    <option value="">—</option>
                    {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1 text-right">مُعيَّن إلى</label>
                  <select className="w-full border rounded-lg px-2 py-1.5 text-sm text-right" value={editForm.assigned_to} onChange={e => setField('assigned_to', e.target.value)}>
                    <option value="">—</option>
                    {staff.map(s => <option key={s.id} value={s.id}>{s.full_name || s.username}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1 text-right">الموعد النهائي</label>
                  <input type="date" className="w-full border rounded-lg px-2 py-1.5 text-sm text-right" value={editForm.due_date} onChange={e => setField('due_date', e.target.value)} />
                </div>
              </div>
            ) : (
              <dl className="space-y-2 text-sm">
                {[
                  ['الحالة',       <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${s.color}`}>{s.label}</span>],
                  ['الأولوية',     PRIORITY_LABELS[task.priority] || '—'],
                  ['النوع',        TYPE_LABELS[task.task_type] || '—'],
                  ['الفرع',        task.branch_name || '—'],
                  ['مُعيَّن إلى',  task.assigned_to_name || '—'],
                  ['أُنشئ بواسطة', task.created_by_name || '—'],
                  ['الموعد النهائي', fmt(task.due_date)],
                  ['تاريخ البدء',  fmt(task.start_date)],
                  ['ساعات مقدَّرة', task.estimated_hours ? `${task.estimated_hours} ساعة` : '—'],
                  ['ساعات فعلية',  task.actual_hours ? `${task.actual_hours} ساعة` : '—'],
                  ...(task.completed_at ? [['أُكمل بواسطة', task.completed_by_name || '—'], ['وقت الاكتمال', fmtTime(task.completed_at)]] : []),
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between items-start gap-2">
                    <span className="text-gray-500 text-right">{k}</span>
                    <span className="text-gray-800 font-medium text-right">{typeof v === 'string' ? v : v}</span>
                  </div>
                ))}
              </dl>
            )}
          </div>

          {/* Assignments */}
          <Section title="الفريق" icon="👥">
            <AssignmentsPanel
              taskId={id}
              assignments={task.assignments || []}
              staff={staff}
              onRefresh={loadTask}
            />
          </Section>

          {/* Related link */}
          {task.related_model && task.related_id && (
            <div className="bg-white rounded-xl border border-gray-200 p-4 text-right">
              <p className="text-xs text-gray-500 mb-1">مرتبط بـ</p>
              <button
                onClick={() => navigate(`/${task.related_model}s/${task.related_id}`)}
                className="text-sm text-brand-600 hover:underline"
              >
                {task.related_model} #{task.related_id}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Complete Modal ── */}
      {showComplete && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5">
            <h3 className="font-bold text-gray-800 text-lg mb-3">إغلاق المهمة</h3>
            <p className="text-sm text-gray-600 mb-3">هل تريد إغلاق وإتمام هذه المهمة؟</p>
            <textarea
              className="w-full border rounded-lg px-3 py-2 text-sm text-right resize-none mb-3"
              rows={3}
              placeholder="ملاحظات الإغلاق (اختياري)..."
              value={completeNotes}
              onChange={e => setCompleteNotes(e.target.value)}
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowComplete(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg">إلغاء</button>
              <button
                onClick={completeTask}
                disabled={completing}
                className="px-5 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium disabled:opacity-50"
              >
                {completing ? '...' : 'تأكيد الإغلاق'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
