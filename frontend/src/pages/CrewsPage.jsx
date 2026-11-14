/**
 * CrewsPage — الأطقم (crews piece 2a, 2026-11-13). Route /crews.
 *
 * A crew says WHO (a set of people), a branch says WHERE. Members come from dated rules (job title,
 * branch, department, section) and dated manual rows; an off-payroll member is a bare SOFTECH user
 * code or extension. Tabs: crews (list + editor), members on a day, history, «بائع غير محدد».
 *
 * The server decides everything (RBAC module `crews`: view to read, edit to change; month lock; void
 * vs end; delete vs archive). This page only shows decisions and sends choices; edit controls are
 * hidden without crews edit, and the server refuses anyway.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { crewsApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import { usePermissions } from '../hooks/usePermission'
import usePermissionStore from '../store/permissionStore'
import useAuthStore from '../store/authStore'
import CrewList from './crews/CrewList'
import CrewEditor from './crews/CrewEditor'
import CrewMembers from './crews/CrewMembers'
import CrewHistory from './crews/CrewHistory'
import UnattributedSales from './crews/UnattributedSales'
import { INPUT, errText } from './crews/util'

const TABS = [
  { key: 'crews',        label: '👥 الأطقم' },
  { key: 'members',      label: '👤 الأعضاء' },
  { key: 'history',      label: '📜 السجل' },
  { key: 'unattributed', label: '🧾 بائع غير محدد' },
]

/** The crew picker of the Members and History tabs (same list as the Crews tab). */
function CrewPicker({ crews, value, onChange }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-gray-600">الطاقم</span>
      <select className={INPUT} value={value ?? ''} onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">— اختر طاقمًا —</option>
        {crews.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </label>
  )
}

export default function CrewsPage() {
  const isAdmin = useAuthStore(s => s.user?.role) === 'admin'
  const perms = usePermissions('crews')
  const loaded = usePermissionStore(s => s.permissions) !== null
  const canView = isAdmin || !!perms.view
  const canEdit = isAdmin || !!perms.edit

  const [tab, setTab] = useState('crews')
  useHelpTab(tab)
  const [archived, setArchived] = useState(false)
  const [selectedId, setSelectedId] = useState(null)

  const list = useQuery({
    queryKey: ['crews', 'list', archived],
    queryFn: () => crewsApi.list(archived).then(r => r.data),
    enabled: canView,
  })
  const crews = list.data || []

  if (!loaded && !isAdmin) return <div dir="rtl" className="p-6 text-sm text-gray-500">جارٍ التحميل…</div>
  if (!canView) return <div dir="rtl" className="p-6 text-sm text-gray-500">لا تملك صلاحية عرض الأطقم.</div>

  return (
    <div className="p-4 md:p-6 space-y-4" dir="rtl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">👥 الأطقم</h1>
        <p className="text-xs text-gray-500 mt-1">
          الطاقم = مَن، والفرع = أين. العضوية مؤرخة، وكل تعديل يبدأ من تاريخ ولا يغيّر الشهور المقفلة.
        </p>
      </div>

      <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1 w-fit" data-tour="crews-main-tabs" role="tablist">
        {TABS.map(t => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
                  className={`px-3 py-1.5 rounded-md text-sm ${tab === t.key ? 'bg-white shadow text-brand-700 font-semibold' : 'text-gray-600 hover:text-gray-900'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {list.isError && <p className="text-sm text-red-600">{errText(list.error)}</p>}

      {tab === 'crews' && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-start">
          <CrewList query={list} selectedId={selectedId} onSelect={setSelectedId}
                    archived={archived} onArchived={v => { setArchived(v); setSelectedId(null) }} canEdit={canEdit} />
          {selectedId
            ? <CrewEditor key={selectedId} crewId={selectedId} canEdit={canEdit} onGone={() => setSelectedId(null)} />
            : <div className="card p-6 text-sm text-gray-500">اختر طاقمًا من القائمة لعرض قواعده وأعضائه.</div>}
        </div>
      )}

      {(tab === 'members' || tab === 'history') && (
        <CrewPicker crews={crews} value={selectedId} onChange={setSelectedId} />
      )}
      {tab === 'members' && (selectedId
        ? <CrewMembers key={selectedId} crewId={selectedId} />
        : <p className="text-sm text-gray-500">اختر طاقمًا لعرض أعضائه.</p>)}
      {tab === 'history' && (selectedId
        ? <CrewHistory key={selectedId} crewId={selectedId} />
        : <p className="text-sm text-gray-500">اختر طاقمًا لعرض سجله.</p>)}

      {tab === 'unattributed' && <UnattributedSales canEdit={canEdit} />}
    </div>
  )
}
