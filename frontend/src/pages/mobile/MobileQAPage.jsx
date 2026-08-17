/**
 * MobileQAPage.jsx — branch QA walk-through inspections (route: /m/qa).
 *
 * Quality manager lists recent inspections and starts a new walk-through
 * (pick template + branch → fill checklist on the detail page). Reuses apps/qa.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { qaApi, branchesApi } from '../../api/client'
import useAuthStore from '../../store/authStore'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'

function scoreClass(s) {
  if (s == null) return 'bg-gray-100 text-gray-600'
  if (s >= 90) return 'bg-green-100 text-green-700'
  if (s >= 70) return 'bg-amber-100 text-amber-700'
  return 'bg-red-100 text-red-700'
}
function toLatin(s) { return s == null ? '' : String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) }

export default function MobileQAPage() {
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const { user } = useAuthStore()
  const canPickBranch = ['admin', 'quality_manager', 'supervisor', 'call_center'].includes(user?.role)

  const [creating, setCreating] = useState(false)
  const [tpl, setTpl]       = useState('')
  const [branch, setBranch] = useState(user?.branch_id ? String(user.branch_id) : '')
  const [busy, setBusy]     = useState(false)
  const [error, setError]   = useState('')

  const inspections = useQuery({
    queryKey: ['m-qa'],
    queryFn: () => qaApi.list({ page_size: 30 }).then(r => r.data),
  })
  const templates = useQuery({
    queryKey: ['qa-templates'],
    queryFn: () => qaApi.templates().then(r => r.data?.results || r.data),
    enabled: creating,
  })
  const branches = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => { const d = r.data; return Array.isArray(d) ? d : (d.results ?? []) }),
    enabled: creating && canPickBranch,
  })

  const rows = Array.isArray(inspections.data) ? inspections.data : (inspections.data?.results || [])
  const tplList = Array.isArray(templates.data) ? templates.data : []

  async function start() {
    const templateId = tpl || tplList[0]?.id
    if (!templateId) { setError('لا يوجد قالب'); return }
    if (!branch) { setError('حدّد الفرع'); return }
    setBusy(true); setError('')
    try {
      const { data } = await qaApi.create({ template: Number(templateId), branch: Number(branch) })
      qc.invalidateQueries({ queryKey: ['m-qa'] })
      navigate(`/m/qa/${data.id}`)
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر إنشاء المراجعة')
      setBusy(false)
    }
  }

  return (
    <div className="p-3 space-y-3">
      {creating && (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-3">
          <h2 className="font-semibold text-gray-700 text-sm">مراجعة جديدة</h2>
          <div>
            <label className="label">القالب</label>
            <select className="input-field w-full" value={tpl} onChange={e => setTpl(e.target.value)}>
              {tplList.map(t => <option key={t.id} value={t.id}>{t.name_ar || t.name}</option>)}
            </select>
          </div>
          {canPickBranch ? (
            <div>
              <label className="label">الفرع *</label>
              <select className="input-field w-full" value={branch} onChange={e => setBranch(e.target.value)}>
                <option value="">اختر الفرع...</option>
                {(branches.data || []).map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
              </select>
            </div>
          ) : (
            <div><label className="label">الفرع</label><div className="input-field bg-gray-50 text-gray-600">{user?.branch_name || 'فرعك'}</div></div>
          )}
          {error && <div className="text-sm text-red-600">{error}</div>}
          <div className="flex gap-2">
            <button onClick={() => setCreating(false)} className="btn-secondary flex-1">إلغاء</button>
            <button onClick={start} disabled={busy} className="btn-primary flex-1 disabled:opacity-50">{busy ? '...' : 'ابدأ المراجعة'}</button>
          </div>
        </div>
      )}

      {inspections.isLoading ? <MobileLoading />
        : inspections.isError ? <MobileError text="تعذّر تحميل المراجعات" onRetry={inspections.refetch} />
        : rows.length === 0 ? <MobileEmpty icon="✔️" text="لا توجد مراجعات بعد" />
        : (
          <div className="space-y-2.5">
            {rows.map(r => (
              <button key={r.id} onClick={() => navigate(`/m/qa/${r.id}`)}
                className="w-full text-right bg-white rounded-2xl border border-gray-200 p-4 active:bg-gray-50">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-bold text-sm text-gray-900">{r.branch_name || `فرع ${r.branch}`}</span>
                  {r.status === 'submitted'
                    ? <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold ${scoreClass(r.score)}`}>{r.score != null ? `${toLatin(r.score)}%` : 'مُرسَلة'}</span>
                    : <span className="text-[11px] px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-600">مسودة</span>}
                </div>
                <div className="flex items-center justify-between text-xs text-gray-400 mt-1">
                  <span>{r.template_name}{r.inspector_name ? ` · ${r.inspector_name}` : ''}</span>
                  <span>{r.created_at ? new Date(r.created_at).toLocaleDateString('en-GB') : ''}</span>
                </div>
              </button>
            ))}
          </div>
        )}

      {!creating && (
        <button onClick={() => { setCreating(true); setError('') }}
          className="fixed bottom-20 left-4 z-20 w-14 h-14 rounded-full bg-brand-600 text-white shadow-lg shadow-brand-900/30 flex items-center justify-center text-2xl active:bg-brand-700"
          title="مراجعة جديدة">+</button>
      )}
    </div>
  )
}
