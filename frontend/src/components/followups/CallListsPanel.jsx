import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { followupsApi } from '../../api/client'
import useAuthStore from '../../store/authStore'

const SEGMENTS = [
  ['vip', 'VIP 👑'], ['loyal', 'مخلص 💚'], ['regular', 'عادي'], ['at_risk', 'في خطر ⚠️'],
  ['dormant', 'نائم 💤'], ['new', 'جديد 🌱'], ['churned', 'مفقود ❌'],
]
const CREATORS = ['admin', 'supervisor', 'call_center']

function NewListForm({ branches, onDone }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [script, setScript] = useState('')
  const [segments, setSegments] = useState(['at_risk'])
  const [branchId, setBranchId] = useState('')
  const [minDays, setMinDays] = useState('30')
  const [maxDays, setMaxDays] = useState('')
  const [agentIds, setAgentIds] = useState([])
  const criteria = {
    segments, ...(branchId && { branch_id: branchId }),
    ...(minDays !== '' && { inactive_days_min: minDays }), ...(maxDays !== '' && { inactive_days_max: maxDays }),
  }

  const { data: agents = [] } = useQuery({
    queryKey: ['call-list-agents'], queryFn: () => followupsApi.callListAgents().then(r => r.data),
  })
  const [preview, setPreview] = useState(null)
  const key = JSON.stringify(criteria)
  useEffect(() => {
    const t = setTimeout(() => {
      followupsApi.callListPreview(criteria).then(r => setPreview(r.data)).catch(() => setPreview(null))
    }, 400)
    return () => clearTimeout(t)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  const create = useMutation({
    mutationFn: () => followupsApi.callListCreate({ name, script, criteria, agent_ids: agentIds }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['call-lists'] })
      qc.invalidateQueries({ queryKey: ['followup-tasks'] })
      qc.invalidateQueries({ queryKey: ['followup-grouped'] })
      onDone()
    },
  })
  const toggle = (list, setList, v) => setList(list.includes(v) ? list.filter(x => x !== v) : [...list, v])

  return (
    <div className="card space-y-3 text-sm">
      <div className="grid md:grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs text-gray-500">اسم القائمة</span>
          <input value={name} onChange={e => setName(e.target.value)} className="input w-full" placeholder="مثال: استرجاع عملاء نوفمبر" />
        </label>
        <label className="block">
          <span className="text-xs text-gray-500">الفرع (اختياري)</span>
          <select value={branchId} onChange={e => setBranchId(e.target.value)} className="input w-full">
            <option value="">كل الفروع المسموحة</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
        </label>
      </div>

      <div>
        <div className="text-xs text-gray-500 mb-1">الشريحة</div>
        <div className="flex flex-wrap gap-1.5">
          {SEGMENTS.map(([v, l]) => (
            <button key={v} type="button" onClick={() => toggle(segments, setSegments, v)}
              className={`px-2.5 py-1 rounded-full text-xs border ${segments.includes(v)
                ? 'bg-gray-800 text-white border-gray-800' : 'border-gray-200 text-gray-600'}`}>{l}</button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <label className="text-xs text-gray-500">لم يشترِ منذ (يوم) على الأقل
          <input type="number" min="0" value={minDays} onChange={e => setMinDays(e.target.value)} className="input w-24 block" />
        </label>
        <label className="text-xs text-gray-500">وعلى الأكثر
          <input type="number" min="0" value={maxDays} onChange={e => setMaxDays(e.target.value)} className="input w-24 block" />
        </label>
        {preview && (
          <span className="text-xs text-gray-600 dark:text-gray-300 pb-2">
            يطابق <b>{preview.matching}</b> عميل
            {preview.capped && ` — سيُنشأ أول ${preview.cap} فقط (الأعلى قيمة)`}
          </span>
        )}
      </div>

      <label className="block">
        <span className="text-xs text-gray-500">نص المكالمة (يظهر للموظف مع كل عميل)</span>
        <textarea value={script} onChange={e => setScript(e.target.value)} rows={3} className="input w-full" />
      </label>

      <div>
        <div className="text-xs text-gray-500 mb-1">الموظفون (توزَّع القائمة عليهم بالتساوي)</div>
        <div className="flex flex-wrap gap-1.5 max-h-28 overflow-auto">
          {agents.map(a => (
            <button key={a.id} type="button" onClick={() => toggle(agentIds, setAgentIds, a.id)}
              className={`px-2.5 py-1 rounded-full text-xs border ${agentIds.includes(a.id)
                ? 'bg-brand-600 text-white border-brand-600' : 'border-gray-200 text-gray-600'}`}>{a.name}</button>
          ))}
        </div>
      </div>

      {create.isError && <div className="text-red-600 text-xs">{create.error?.response?.data?.detail || 'فشل الإنشاء'}</div>}
      <div className="flex justify-end gap-2">
        <button onClick={onDone} className="btn-secondary text-sm px-3 py-1.5">إلغاء</button>
        <button onClick={() => create.mutate()}
          disabled={create.isPending || !name.trim() || !agentIds.length || !preview?.matching}
          className="btn-primary text-sm px-4 py-1.5 disabled:opacity-50">
          {create.isPending ? '⏳ جارٍ الإنشاء…' : `إنشاء القائمة (${preview?.will_create ?? 0})`}
        </button>
      </div>
    </div>
  )
}

export default function CallListsPanel({ branches = [], activeListId, onSelectList }) {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const canCreate = CREATORS.includes(user?.role)
  const [showForm, setShowForm] = useState(false)
  const [status, setStatus] = useState('active')
  const { data: lists = [], isLoading } = useQuery({
    queryKey: ['call-lists', status],
    queryFn: () => followupsApi.callLists(status).then(r => r.data),
    refetchInterval: 60_000,
  })
  const close = useMutation({
    mutationFn: (id) => followupsApi.callListClose(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['call-lists'] }); onSelectList(null) },
  })

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex gap-1 text-xs">
          {[['active', 'النشطة'], ['closed', 'المغلقة']].map(([v, l]) => (
            <button key={v} onClick={() => setStatus(v)}
              className={`px-3 py-1 rounded-lg ${status === v ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-600'}`}>{l}</button>
          ))}
        </div>
        {canCreate && !showForm && (
          <button onClick={() => setShowForm(true)} className="btn-primary text-sm px-3 py-1.5">+ قائمة اتصال جديدة</button>
        )}
      </div>

      {showForm && <NewListForm branches={branches} onDone={() => setShowForm(false)} />}

      {isLoading ? <div className="text-xs text-gray-400">جارٍ التحميل…</div> : lists.length === 0 ? (
        <div className="text-xs text-gray-400 py-4 text-center">لا توجد قوائم {status === 'active' ? 'نشطة' : 'مغلقة'}</div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
          {lists.map(cl => (
            <div key={cl.id}
              onClick={() => onSelectList(activeListId === cl.id ? null : cl.id)}
              className={`card cursor-pointer text-sm space-y-2 ${activeListId === cl.id ? 'ring-2 ring-brand-500' : ''}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold truncate">{cl.name}</span>
                <span className="text-xs text-gray-400">{cl.created_by}</span>
              </div>
              <div className="h-2 rounded-full bg-gray-100 dark:bg-gray-700 overflow-hidden">
                <div className="h-full bg-green-500" style={{ width: `${cl.progress.pct}%` }} />
              </div>
              <div className="flex flex-wrap gap-x-3 text-xs text-gray-500">
                <span>{cl.progress.total} عميل</span>
                <span>لم يُتصل: {cl.progress.open}</span>
                <span>لا رد: {cl.progress.no_answer}</span>
                <span className="text-green-700">تم: {cl.progress.done}</span>
                <span>{cl.progress.pct}%</span>
              </div>
              {cl.script && <div className="text-xs text-gray-500 line-clamp-2">📝 {cl.script}</div>}
              {canCreate && cl.status === 'active' && (
                <div className="flex justify-end">
                  <button onClick={(e) => { e.stopPropagation(); if (confirm(`إغلاق «${cl.name}»؟ تُلغى المكالمات التي لم تتم.`)) close.mutate(cl.id) }}
                    className="text-xs text-red-600 hover:underline">إغلاق القائمة</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {activeListId && <div className="text-xs text-gray-500">المهام أدناه هي عملاء القائمة المختارة — اضغط على القائمة مرة أخرى لإلغاء الاختيار.</div>}
    </section>
  )
}
