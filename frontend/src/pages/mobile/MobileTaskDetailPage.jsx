/**
 * MobileTaskDetailPage.jsx — task detail (route: /m/tasks/:id).
 * Shows description + checklist (read), a "complete" action, and a chatter thread.
 */
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { tasksApi } from '../../api/client'
import MobileChatter from '../../components/MobileChatter'
import { MobileLoading, MobileError } from '../../components/mobileUi'

export default function MobileTaskDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const qc       = useQueryClient()

  const { data: t, isLoading, isError, refetch } = useQuery({
    queryKey: ['m-task', id],
    queryFn: () => tasksApi.get(id).then(r => r.data),
  })
  const msgs = useQuery({
    queryKey: ['m-task-msgs', id],
    queryFn: () => tasksApi.getMessages(id).then(r => r.data).catch(() => []),
    enabled: !!id,
  })

  async function complete() {
    await tasksApi.complete(id)
    await qc.invalidateQueries({ queryKey: ['m-task', id] })
    qc.invalidateQueries({ queryKey: ['m-tasks'] })
  }
  async function sendNote(text) {
    await tasksApi.sendMessage(id, text)
    await qc.invalidateQueries({ queryKey: ['m-task-msgs', id] })
  }

  if (isLoading) return <MobileLoading />
  if (isError || !t) return <MobileError text="تعذّر تحميل المهمة" onRetry={refetch} />

  const items = t.items || []
  const messages = (Array.isArray(msgs.data) ? msgs.data : (msgs.data?.results || []))
    .map(m => ({ id: m.id, text: m.body || m.message, who: m.author_name || m.created_by_name, when: m.created_at }))
  const isDone = ['done', 'completed', 'closed'].includes(t.status)

  return (
    <div className="p-3 space-y-3">
      <button onClick={() => navigate('/m/tasks')} className="text-sm text-gray-500">→ الرجوع للمهام</button>

      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-start justify-between gap-2 mb-1">
          <h1 className="font-bold text-base text-gray-900">{t.title}</h1>
          <span className="text-[11px] px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-700 shrink-0">{t.status_label || t.status}</span>
        </div>
        {t.description && <p className="text-sm text-gray-600 mt-1 whitespace-pre-wrap">{t.description}</p>}
        {t.due_date && <p className="text-xs text-gray-400 mt-1">يستحق: {t.due_date}</p>}
      </div>

      {items.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <h2 className="font-semibold text-gray-700 text-sm mb-2.5">قائمة التحقق</h2>
          <div className="space-y-1.5">
            {items.map(it => {
              const done = it.is_done ?? it.done ?? it.completed
              return (
                <div key={it.id} className="flex items-center gap-2 text-sm">
                  <span>{done ? '☑️' : '⬜'}</span>
                  <span className={done ? 'text-gray-400 line-through' : 'text-gray-700'}>{it.text || it.title || it.label}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {!isDone && (
        <button onClick={complete} className="btn-primary w-full py-3">✅ إنهاء المهمة</button>
      )}

      <MobileChatter messages={messages} onSend={sendNote} title="💬 المحادثة" />
    </div>
  )
}
