/**
 * AccessPanel — admin only: which named branch managers may open PIC Analytics (doc 33 §5).
 * Inline and calm: list the active grants, search staff, grant, revoke. The server enforces
 * everything; every change is audited there.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { picAnalyticsApi } from '../../api/client'
import { fmtDate } from './KpiCards'

export default function AccessPanel() {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')
  const grants = useQuery({ queryKey: ['pic-analytics', 'grants'], queryFn: () => picAnalyticsApi.grants().then(r => r.data.rows) })
  const cands = useQuery({
    queryKey: ['pic-analytics', 'candidates', q],
    queryFn: () => picAnalyticsApi.candidates(q).then(r => r.data.rows),
    enabled: q.trim().length >= 2,
  })
  const done = () => { setErr(''); qc.invalidateQueries({ queryKey: ['pic-analytics', 'grants'] }); qc.invalidateQueries({ queryKey: ['pic-analytics', 'candidates'] }) }
  const fail = e => setErr(e?.response?.data?.detail || 'تعذّر تنفيذ العملية')
  const grant = useMutation({ mutationFn: id => picAnalyticsApi.grant({ staff_id: id }), onSuccess: done, onError: fail })
  const revoke = useMutation({ mutationFn: id => picAnalyticsApi.revoke(id), onSuccess: done, onError: fail })
  const active = (grants.data || []).filter(g => !g.revoked_at)

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3" data-tour="pic-analytics-access">
      <div>
        <h3 className="text-sm font-bold text-gray-700">صلاحية مديري الفروع</h3>
        <p className="text-xs text-gray-400">مدير الفرع المُصرَّح له يرى فرعه فقط، بدون التكلفة أو الربح.</p>
      </div>
      {err && <p className="text-xs text-red-600">{err}</p>}
      <div className="space-y-1">
        {active.length === 0 && <p className="text-xs text-gray-400">لا أحد مُصرَّح له حالياً</p>}
        {active.map(g => (
          <div key={g.id} className="flex items-center justify-between text-xs border-b border-gray-100 py-1.5">
            <span><b>{g.staff_name}</b> · {g.branch || '—'} · منذ {fmtDate(g.granted_at)}{g.granted_by ? ` بواسطة ${g.granted_by}` : ''}</span>
            <button className="text-red-600 hover:underline" disabled={revoke.isPending} onClick={() => revoke.mutate(g.id)}>إلغاء الصلاحية</button>
          </div>
        ))}
      </div>
      <div>
        <input className="input-field text-xs py-1.5 w-64" placeholder="ابحث عن موظف لمنحه الصلاحية…"
               value={q} onChange={e => setQ(e.target.value)} />
        <div className="mt-1 space-y-1">
          {(cands.data || []).map(c => (
            <div key={c.id} className="flex items-center justify-between text-xs py-1 max-w-md">
              <span>{c.name} · {c.branch || '—'}</span>
              {c.granted
                ? <span className="text-gray-400">مُصرَّح له</span>
                : <button className="btn-secondary text-xs py-0.5" disabled={grant.isPending} onClick={() => grant.mutate(c.id)}>منح</button>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
