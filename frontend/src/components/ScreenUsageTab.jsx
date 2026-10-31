/**
 * ScreenUsageTab — /audit → «استخدام الشاشات» (P-57).
 *
 * Screens / modules over the last N days, screens nobody opened in 60 days (from the
 * menu's own routes), and — admin / HR only, enforced by the server — per staff
 * member. Usage alone is never a performance verdict: read it next to the outcome
 * KPIs (identified sales, refills, QA score).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi } from '../api/client'
import { NAV_GROUPS } from './Layout'

const KNOWN_ROUTES = [...new Set(NAV_GROUPS.flatMap(g => (g.items || []).map(i => i.to)))]
const VIEWS = [['screens', 'الشاشات'], ['modules', 'الأقسام'], ['staff', 'الموظفين']]

export default function ScreenUsageTab() {
  const [view, setView] = useState('screens')
  const [days, setDays] = useState(28)
  const { data, error, isLoading } = useQuery({
    queryKey: ['screen-usage', view, days],
    queryFn: () => auditApi.usage({ view, days, ...(view === 'screens' ? { known: KNOWN_ROUTES.join(',') } : {}) })
      .then(r => r.data),
    retry: false,
  })
  const denied = error?.response?.status === 403
  const rows = data?.rows || []

  return (
    <div className="space-y-4" data-tour="admin-audit-usage">
      <div className="flex flex-wrap items-center gap-2">
        {VIEWS.map(([k, label]) => (
          <button key={k} onClick={() => setView(k)}
            className={`px-3 py-1.5 rounded-lg text-sm border ${view === k ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600 border-gray-200'}`}>
            {label}
          </button>
        ))}
        <select value={days} onChange={e => setDays(Number(e.target.value))}
          className="mr-auto text-sm border border-gray-200 rounded-lg px-2 py-1.5 bg-white">
          {[7, 28, 90].map(d => <option key={d} value={d}>آخر {d} يوم</option>)}
        </select>
      </div>

      <p className="text-xs text-gray-500">
        الاستخدام وحده مش حكم على أداء حد — اقراه جنب نتائج الشغل (البيع المعرّف، المتابعات، تقييم الجودة).
      </p>

      {denied && <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
        {view === 'staff' ? 'التقرير الفردي للإدارة والموارد البشرية فقط.' : 'ليس لديك صلاحية لهذا التقرير.'}
      </div>}
      {isLoading && <div className="text-sm text-gray-400">جارٍ التحميل…</div>}

      {!denied && !isLoading && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs">
              {view === 'screens' && <tr><th className="p-2 text-right">الشاشة</th><th className="p-2">مرات الفتح</th><th className="p-2">عدد المستخدمين</th></tr>}
              {view === 'modules' && <tr><th className="p-2 text-right">القسم</th><th className="p-2">مستخدمون هذا الأسبوع</th><th className="p-2">مرات الفتح</th></tr>}
              {view === 'staff' && <tr><th className="p-2 text-right">الموظف</th><th className="p-2">الدور</th><th className="p-2">الفرع</th><th className="p-2">مرات الفتح</th><th className="p-2">شاشات مختلفة</th><th className="p-2">آخر استخدام</th></tr>}
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-gray-100">
                  {view === 'screens' && <><td className="p-2 font-mono text-xs" dir="ltr">{r.route}</td><td className="p-2 text-center">{r.visits}</td><td className="p-2 text-center">{r.users}</td></>}
                  {view === 'modules' && <><td className="p-2 font-mono text-xs" dir="ltr">/{r.module}</td><td className="p-2 text-center">{r.weekly_active_users}</td><td className="p-2 text-center">{r.visits}</td></>}
                  {view === 'staff' && <><td className="p-2">{r.name}</td><td className="p-2 text-center">{r.role}</td><td className="p-2 text-center">{r.branch}</td><td className="p-2 text-center">{r.visits}</td><td className="p-2 text-center">{r.screens}</td><td className="p-2 text-center text-xs">{r.last_at ? new Date(r.last_at).toLocaleDateString('en-GB') : '—'}</td></>}
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={6} className="p-4 text-center text-gray-400">لا يوجد استخدام مسجّل في الفترة دي</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {view === 'screens' && data?.zero_use?.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-3" data-tour="admin-audit-usage-zero">
          <div className="text-sm font-bold text-gray-700 mb-2">شاشات محدش فتحها من ٦٠ يوم ({data.zero_use.length})</div>
          <div className="flex flex-wrap gap-1.5">
            {data.zero_use.map(r => <span key={r} dir="ltr" className="font-mono text-xs bg-gray-100 rounded px-2 py-0.5">{r}</span>)}
          </div>
        </div>
      )}
    </div>
  )
}
