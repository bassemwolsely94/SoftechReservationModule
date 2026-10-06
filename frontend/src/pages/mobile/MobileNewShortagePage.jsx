/**
 * MobileNewShortagePage.jsx — create a shortage list (route: /m/shortage/new).
 *
 * Minimal: branch (default user's, editable for HQ roles) + optional title, then
 * straight into the detail page to start logging items.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { shortageApi, branchesApi } from '../../api/client'
import useAuthStore from '../../store/authStore'

export default function MobileNewShortagePage() {
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const { user } = useAuthStore()
  const canPickBranch = ['admin', 'purchasing', 'call_center'].includes(user?.role)

  const [branch, setBranch] = useState(user?.branch_id ? String(user.branch_id) : '')
  const [title, setTitle]   = useState('')
  const [busy, setBusy]     = useState(false)
  const [error, setError]   = useState('')

  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => {
      const d = r.data
      return Array.isArray(d) ? d : (d.results ?? [])
    }),
    enabled: canPickBranch,
  })

  async function create() {
    if (!branch) { setError('حدّد الفرع'); return }
    setBusy(true); setError('')
    try {
      const { data } = await shortageApi.create({ branch: Number(branch), title })
      qc.invalidateQueries({ queryKey: ['m-shortage'] })
      navigate(`/m/shortage/${data.id}`, { replace: true })
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر إنشاء القائمة')
      setBusy(false)
    }
  }

  return (
    <div className="p-3 space-y-3">
      <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-4">
        <h2 className="font-semibold text-gray-700 text-sm">🚨 قائمة نواقص جديدة</h2>
        {canPickBranch ? (
          <div>
            <label className="label">الفرع *</label>
            <select className="input-field w-full" value={branch} onChange={e => setBranch(e.target.value)}>
              <option value="">اختر الفرع...</option>
              {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          </div>
        ) : (
          <div>
            <label className="label">الفرع</label>
            <div className="input-field bg-gray-50 text-gray-600">{user?.branch_name || 'فرعك الحالي'}</div>
          </div>
        )}
        <div>
          <label className="label">العنوان (اختياري)</label>
          <input className="input-field w-full" value={title} onChange={e => setTitle(e.target.value)}
            placeholder="مثال: نواقص الجرد الأسبوعي" />
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-2xl px-4 py-3">{error}</div>}

      <div className="flex gap-2.5">
        <button onClick={() => navigate('/m/shortage')} className="btn-secondary px-5">إلغاء</button>
        <button onClick={create} disabled={busy} className="btn-primary flex-1 py-3 disabled:opacity-50">
          {busy ? 'جارٍ الإنشاء...' : 'إنشاء وبدء التسجيل'}
        </button>
      </div>
    </div>
  )
}
