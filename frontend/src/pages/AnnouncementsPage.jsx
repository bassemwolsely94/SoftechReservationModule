/**
 * AnnouncementsPage.jsx — /announcements
 * HQ → branch internal broadcasts with read-acknowledgement.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notificationsApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'

const ROLES = [
  ['admin', 'مدير'], ['supervisor', 'مشرف'], ['pharmacist', 'صيدلي'], ['salesperson', 'مندوب'],
  ['call_center', 'مركز اتصال'], ['purchasing', 'مشتريات'], ['delivery', 'توصيل'],
  ['quality_manager', 'جودة'], ['viewer', 'عرض'],
]

export default function AnnouncementsPage() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canBroadcast = ['admin', 'supervisor'].includes(user?.role)
  const [showForm, setShowForm] = useState(false)
  const [statsFor, setStatsFor] = useState(null)

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['announcements'],
    queryFn: () => notificationsApi.announcements().then(r => Array.isArray(r.data) ? r.data : []),
  })
  const ack = useMutation({
    mutationFn: (id) => notificationsApi.ackAnnouncement(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['announcements'] }),
  })
  const del = useMutation({
    mutationFn: (id) => notificationsApi.deleteAnnouncement(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['announcements'] }),
  })

  return (
    <div className="p-6 max-w-3xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">📢 الإعلانات الداخلية</h1>
          <p className="text-sm text-gray-500 mt-0.5">تعميمات الإدارة للفروع مع تأكيد القراءة</p>
        </div>
        {canBroadcast && (
          <button onClick={() => setShowForm(s => !s)} className="btn-primary text-sm">
            {showForm ? 'إغلاق' : '+ إعلان جديد'}
          </button>
        )}
      </div>

      {showForm && canBroadcast && <AnnForm onDone={() => { setShowForm(false); qc.invalidateQueries({ queryKey: ['announcements'] }) }} />}

      {isLoading ? (
        <div className="text-center py-16 text-gray-400">جارٍ التحميل…</div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-400">لا توجد إعلانات</div>
      ) : (
        <div className="space-y-3">
          {items.map(a => {
            const mine = a.author === user?.staff_profile_id || ['admin', 'supervisor'].includes(user?.role)
            return (
              <div key={a.id} className={`bg-white rounded-2xl border p-4 ${a.priority === 'high' ? 'border-red-200' : 'border-gray-100'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      {a.priority === 'high' && <span className="text-[10px] font-black text-red-600 bg-red-50 rounded px-1.5 py-0.5">هام</span>}
                      <h3 className="font-bold text-gray-900">{a.title}</h3>
                    </div>
                    <p className="text-sm text-gray-600 mt-1 whitespace-pre-wrap leading-relaxed">{a.body}</p>
                    <div className="text-[11px] text-gray-400 mt-2">{a.author_name} · {a.time_ago}</div>
                  </div>
                  <div className="flex flex-col items-end gap-1.5 shrink-0">
                    {a.is_read
                      ? <span className="text-[11px] text-emerald-600 font-medium">✓ مقروء</span>
                      : <button onClick={() => ack.mutate(a.id)} className="text-xs bg-brand-600 text-white rounded-lg px-3 py-1.5 font-medium">تأكيد القراءة</button>}
                    {mine && <button onClick={() => setStatsFor(a.id)} className="text-[11px] text-gray-500 hover:text-gray-800">📊 من قرأ</button>}
                    {mine && <button onClick={() => del.mutate(a.id)} className="text-[11px] text-gray-300 hover:text-red-500">حذف</button>}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {statsFor && <StatsModal id={statsFor} onClose={() => setStatsFor(null)} />}
    </div>
  )
}

function StatsModal({ id, onClose }) {
  const { data } = useQuery({
    queryKey: ['announcement-stats', id],
    queryFn: () => notificationsApi.announcementStats(id).then(r => r.data),
  })
  const pct = data && data.audience_count ? Math.round((data.read_count / data.audience_count) * 100) : 0
  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-black text-gray-900">إحصاء القراءة</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        {!data ? <div className="py-8 text-center text-gray-400 text-sm">جارٍ التحميل…</div> : (
          <>
            <div className="text-center py-2">
              <div className="text-3xl font-black text-brand-700">{data.read_count} / {data.audience_count}</div>
              <div className="text-sm text-gray-500 mt-1">أكّدوا القراءة ({pct}%)</div>
            </div>
            <div className="h-2 rounded-full bg-gray-100 overflow-hidden mt-2">
              <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function AnnForm({ onDone }) {
  const [f, setF] = useState({ title: '', body: '', priority: 'normal', roles: [], branches: [] })
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
  })
  const create = useMutation({
    mutationFn: (data) => notificationsApi.createAnnouncement(data),
    onSuccess: onDone,
  })
  const toggle = (key, val) => setF(s => {
    const arr = new Set(s[key]); arr.has(val) ? arr.delete(val) : arr.add(val); return { ...s, [key]: [...arr] }
  })
  function submit() {
    create.mutate({
      title: f.title, body: f.body, priority: f.priority,
      audience_roles: f.roles, audience_branch_ids: f.branches,
    })
  }
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-4 mb-4 space-y-3">
      <input className="input-field" placeholder="عنوان الإعلان" value={f.title} onChange={e => setF(s => ({ ...s, title: e.target.value }))} />
      <textarea className="input-field min-h-[90px]" placeholder="نص الإعلان…" value={f.body} onChange={e => setF(s => ({ ...s, body: e.target.value }))} />
      <div>
        <div className="text-xs font-semibold text-gray-500 mb-1">الأدوار المستهدفة (فارغ = الجميع)</div>
        <div className="flex flex-wrap gap-1.5">
          {ROLES.map(([v, l]) => (
            <button key={v} type="button" onClick={() => toggle('roles', v)}
              className={`text-xs rounded-lg px-2.5 py-1 border ${f.roles.includes(v) ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-200'}`}>{l}</button>
          ))}
        </div>
      </div>
      <div>
        <div className="text-xs font-semibold text-gray-500 mb-1">الفروع المستهدفة (فارغ = كل الفروع)</div>
        <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
          {branches.map(b => (
            <button key={b.id} type="button" onClick={() => toggle('branches', b.id)}
              className={`text-xs rounded-lg px-2.5 py-1 border ${f.branches.includes(b.id) ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-200'}`}>{b.name_ar || b.name}</button>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between">
        <label className="text-sm flex items-center gap-2">
          <input type="checkbox" checked={f.priority === 'high'} onChange={e => setF(s => ({ ...s, priority: e.target.checked ? 'high' : 'normal' }))} className="accent-red-600" />
          إعلان هام
        </label>
        <button onClick={submit} disabled={!f.title || !f.body || create.isPending} className="btn-primary text-sm disabled:opacity-40">
          {create.isPending ? 'جارٍ النشر…' : 'نشر الإعلان'}
        </button>
      </div>
    </div>
  )
}
