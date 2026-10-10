/**
 * MobileGamificationPage — /m/gamification (التحفيز on the phone).
 * My level + today's points + streak, what is still waiting («لا تترك شيئاً خلفك»),
 * and my branch's monthly ranking. Same API as the desktop page.
 */
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { gamificationApi } from '../../api/client'
import useLangStore from '../../store/langStore'
import { MobileLoading, MobileError } from '../../components/mobileUi'
import { LevelBar, useGamificationMe } from '../../components/GamificationCard'
import { LeaderboardTable } from '../GamificationPage'

// Open items whose screen has a phone version go to /m/…; the rest open the desktop screen.
const MOBILE_ROUTES = new Set(['/reservations', '/tasks', '/demand', '/transfers'])
const signed = (n) => `${n > 0 ? '+' : ''}${(n ?? 0).toLocaleString('en-US')}`

export default function MobileGamificationPage() {
  const navigate = useNavigate()
  const { t, lang } = useLangStore()
  const { data: me, isLoading, isError, refetch } = useGamificationMe()
  const { data: board } = useQuery({
    queryKey: ['gamificationBoard', 'month', 'branch', ''],
    queryFn: () => gamificationApi.leaderboard({ period: 'month', scope: 'branch' }).then(r => r.data),
  })
  if (isLoading) return <div className="p-3"><MobileLoading /></div>
  if (isError || !me) return <div className="p-3"><MobileError text={t('تعذّر التحميل', 'Could not load')} onRetry={refetch} /></div>
  const open = me.open_items || []
  return (
    <div className="p-3 space-y-3" dir={lang === 'en' ? 'ltr' : 'rtl'}>
      <h1 className="text-base font-bold text-gray-900">{t('التحفيز', 'Gamification')}</h1>
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <LevelBar level={me.level} xp={me.xp} t={t} lang={lang} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        {[[t('اليوم', 'Today'), signed(me.points?.day)], [t('الشهر', 'Month'), signed(me.points?.month)],
          [t('أيام نظيفة', 'Clean days'), `🔥 ${me.streak?.current ?? 0}`]].map(([l, v]) => (
          <div key={l} className="bg-white rounded-2xl border border-gray-200 p-3 text-center">
            <div className="text-lg font-bold text-gray-900">{v}</div>
            <div className="text-[11px] text-gray-400">{l}</div>
          </div>
        ))}
      </div>
      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="font-bold text-sm mb-2">{t('🧹 لا تترك شيئاً خلفك', '🧹 Leave nothing behind')}</div>
        {open.length === 0
          ? <p className="text-sm text-emerald-700">{t('لا شيء ينتظرك ✅', 'Nothing waiting ✅')}</p>
          : open.map(i => (
            <button key={i.key} onClick={() => navigate(MOBILE_ROUTES.has(i.route) ? `/m${i.route}` : i.route)}
                    className={`w-full flex justify-between rounded-xl px-3 py-2 mb-1.5 text-sm ${i.penalty ? 'bg-red-50 text-red-800' : 'bg-amber-50 text-amber-800'}`}>
              <span>{lang === 'en' ? i.label_en : i.label_ar}</span><b>{i.count}</b>
            </button>
          ))}
      </div>
      <div className="bg-white rounded-2xl border border-gray-200 p-2">
        <div className="font-bold text-sm p-2">{t('🏆 ترتيب فرعي هذا الشهر', '🏆 My branch this month')}</div>
        <LeaderboardTable rows={board?.rows} meId={me.staff_id} t={t} lang={lang} compact />
      </div>
    </div>
  )
}
