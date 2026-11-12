/**
 * AccessTab — admin only: who besides the admin may open the attendance module (view or manage).
 * Grants and revokes are kept and audited by the server; an error from the server is shown inline.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { hrAttendanceApi } from '../../api/client'
import { BTN, Empty, Notice, TH, errText, stamp } from './shared'

const LEVEL = { view: 'عرض', manage: 'إدارة' }

export default function AccessTab() {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [level, setLevel] = useState('view')
  const list = useQuery({ queryKey: ['hr-attendance', 'grants'], queryFn: () => hrAttendanceApi.grants().then(r => r.data.rows) })
  const search = q.trim()
  const cands = useQuery({
    queryKey: ['hr-attendance', 'grants', 'candidates', search], enabled: search.length >= 2,
    queryFn: () => hrAttendanceApi.grants({ q: search }).then(r => r.data.candidates || []),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['hr-attendance', 'grants'] })
  const grant = useMutation({
    mutationFn: staff => hrAttendanceApi.grant({ staff, level }),
    onSuccess: () => { setQ(''); refresh() },
  })
  const revoke = useMutation({ mutationFn: id => hrAttendanceApi.revokeGrant(id), onSuccess: refresh })
  const rows = list.data || []

  return (
    <div data-tour="hr-attendance-access">
      <p className="text-xs text-gray-500 mb-3">المدير يدخل دائماً. من هنا تمنح شخصاً بعينه «عرض» (يرى ويصدّر) أو «إدارة» (يقرر الربط والأرقام المجهولة والتجميع).</p>
      <div className="mb-4 rounded-xl border border-gray-200 bg-white p-3">
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <label className="flex flex-col text-xs text-gray-500">ابحث عن مستخدم
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="الاسم أو اسم المستخدم"
              className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
          </label>
          <label className="flex flex-col text-xs text-gray-500">المستوى
            <select value={level} onChange={e => setLevel(e.target.value)}
              className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
              <option value="view">عرض</option><option value="manage">إدارة</option>
            </select>
          </label>
          <Notice>{grant.isError ? errText(grant.error) : ''}{cands.isError ? errText(cands.error) : ''}</Notice>
        </div>
        {search.length >= 2 && (
          <ul className="mt-2 divide-y divide-gray-100 text-sm">
            {(cands.data || []).map(c => (
              <li key={c.id} className="flex items-center gap-2 py-1.5">
                <span>{c.name}</span>
                <button type="button" disabled={grant.isPending} onClick={() => grant.mutate(c.id)}
                  className={`${BTN} ms-auto bg-primary text-white`}>منح «{LEVEL[level]}»</button>
              </li>
            ))}
            {cands.data && cands.data.length === 0 && <li className="py-2 text-xs text-gray-400">لا نتائج</li>}
          </ul>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <th className={TH}>المستخدم</th><th className={TH}>المستوى</th><th className={TH}>مُنحت</th>
              <th className={TH}>بواسطة</th><th className={TH}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(g => (
              <tr key={g.id} className={`border-b border-gray-100 ${g.revoked_at ? 'opacity-50' : ''}`}>
                <td className="px-3 py-2 font-medium">{g.staff?.name || '—'}</td>
                <td className="px-3 py-2">{LEVEL[g.level] || g.level}</td>
                <td className="px-3 py-2 text-gray-600">{stamp(g.granted_at)}</td>
                <td className="px-3 py-2 text-gray-600">{g.granted_by || '—'}</td>
                <td className="px-3 py-2">
                  {g.revoked_at
                    ? <span className="text-xs text-gray-400">أُلغيت {stamp(g.revoked_at)}</span>
                    : <button type="button" disabled={revoke.isPending} onClick={() => revoke.mutate(g.id)}
                        className={`${BTN} bg-white border border-red-200 text-red-700 hover:bg-red-50`}>إلغاء</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.isLoading && <Empty>جاري التحميل…</Empty>}
        {list.isError && <div className="py-6 text-center text-sm text-red-600">{errText(list.error)}</div>}
        {!list.isLoading && !list.isError && rows.length === 0 && <Empty>لا توجد صلاحيات ممنوحة بعد</Empty>}
        {revoke.isError && <div className="px-3 py-2"><Notice>{errText(revoke.error)}</Notice></div>}
      </div>
    </div>
  )
}
