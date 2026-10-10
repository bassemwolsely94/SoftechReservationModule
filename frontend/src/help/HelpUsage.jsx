/**
 * HelpUsage — trainers: help that is NOT being used (period = the trainers tab's
 * days). Screens whose help nobody opened (those on a role's training path first),
 * and «اعرض لي» tours: runs, finished %, the step people stop at, tours never run.
 * Numbers come from /api/help/usage/.
 */
import { useQuery } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import { pick } from './text'

export default function HelpUsage({ days, go }) {
  const { data, isLoading } = useQuery({
    queryKey: ['help', 'usage', days],
    queryFn: () => helpApi.usage(days).then((r) => r.data),
  })
  if (isLoading || !data) return <div className="text-sm text-faint">…جارٍ التحميل</div>
  const onPath = data.unopened.filter((u) => u.on_paths.length)
  const others = data.unopened.filter((u) => !u.on_paths.length)
  const neverRun = data.tours.filter((t) => !t.runs)
  const used = data.tours.filter((t) => t.runs)
  const Screen = ({ u }) => (
    <button type="button" onClick={() => go({ tab: 'browse', screen: u.screen_key })}
            className="text-xs border border-line rounded-full px-2.5 py-1 text-content hover:border-brand-300">
      {pick(u.title, 'ar')}
      {u.on_paths.length > 0 && (
        <span className="text-faint" title={u.on_paths.join('، ')}>
          {' · '}{u.on_paths.length > 3 ? `${u.on_paths.length} أدوار` : u.on_paths.join('، ')}
        </span>
      )}
    </button>
  )
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-xl border border-line bg-surface p-4 space-y-3">
        <h3 className="text-sm font-bold text-content">
          شاشات محدش فتح شرحها ({data.unopened.length} من {data.screens_total} في آخر {data.days} يوم)
        </h3>
        {onPath.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-xs font-semibold text-amber-700">في مسارات التدريب — المفروض الناس تكون قرأتها:</div>
            <div className="flex flex-wrap gap-1.5">{onPath.map((u) => <Screen key={u.screen_key} u={u} />)}</div>
          </div>
        )}
        {others.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted">باقي الشاشات ({others.length})</summary>
            <div className="flex flex-wrap gap-1.5 mt-2">{others.map((u) => <Screen key={u.screen_key} u={u} />)}</div>
          </details>
        )}
        {!data.unopened.length && <div className="text-sm text-faint">كل الشاشات اتفتح شرحها 🎉</div>}
      </div>

      <div className="rounded-xl border border-line bg-surface p-4 space-y-3">
        <h3 className="text-sm font-bold text-content">جولات «اعرض لي»</h3>
        {used.length === 0 && <div className="text-sm text-faint">محدش شغّل جولة في الفترة دي.</div>}
        {used.length > 0 && (
          <div className="divide-y divide-line text-sm">
            <div className="grid grid-cols-12 gap-2 py-1 text-[11px] text-faint">
              <span className="col-span-6">الشاشة</span><span className="col-span-2">مرات</span>
              <span className="col-span-2">كمّلوها</span><span className="col-span-2">بيقفوا بعد</span>
            </div>
            {used.map((t) => (
              <div key={t.screen_key} onClick={() => go({ tab: 'browse', screen: t.screen_key })}
                   className="grid grid-cols-12 gap-2 py-1.5 cursor-pointer hover:bg-surface-2">
                <span className="col-span-6 text-content truncate">{pick(t.title, 'ar')}</span>
                <span className="col-span-2 tabnum">{t.runs}</span>
                <span className={`col-span-2 tabnum ${t.done_pct < 50 ? 'text-red-600' : 'text-emerald-700'}`}>{t.done_pct}%</span>
                <span className="col-span-2 text-xs text-muted tabnum">{t.common_stop ? `خطوة ${t.common_stop} / ${t.steps}` : '—'}</span>
              </div>
            ))}
          </div>
        )}
        {used.length > 0 && (
          <div className="text-[11px] text-faint">«بيقفوا بعد خطوة N» = أغلب اللي ما كمّلوش وقفوا هنا — الخطوة اللي بعدها غالباً مش واضحة أو الزر مش ظاهر.</div>
        )}
        {neverRun.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted">جولات محدش شغّلها ({neverRun.length})</summary>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {neverRun.map((t) => <Screen key={t.screen_key} u={{ ...t, on_paths: [] }} />)}
            </div>
          </details>
        )}
      </div>
    </div>
  )
}
