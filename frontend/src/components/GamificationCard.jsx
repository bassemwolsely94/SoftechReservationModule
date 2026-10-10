/**
 * GamificationCard — compact «التحفيز» strip for the home dashboard and لوحتي الشخصية.
 * Level + XP progress, today's / month's points, clean-day streak, branch rank and the
 * "nothing left behind" count. All numbers come from GET /api/gamification/me/.
 */
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { gamificationApi } from '../api/client'
import useLangStore from '../store/langStore'

export function useGamificationMe() {
  return useQuery({
    queryKey: ['gamificationMe'],
    queryFn: () => gamificationApi.me().then(r => r.data),
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  })
}

const fmt = (n) => (n ?? 0).toLocaleString('en-US')
const signed = (n) => `${n > 0 ? '+' : ''}${fmt(n)}`

export function LevelBar({ level, xp, t, lang }) {
  const cur = level?.current
  const next = level?.next
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="text-2xl leading-none">{cur?.icon || '🌱'}</span>
        <div className="min-w-0">
          <div className="text-sm font-black text-gray-900 truncate">
            {lang === 'en' ? cur?.title_en : cur?.title_ar}
            <span className="text-xs font-bold text-gray-400 mx-1">
              · {t('المستوى', 'Level')} {cur?.number ?? 1}
            </span>
          </div>
          <div className="text-xs text-gray-500">{fmt(xp)} {t('نقطة خبرة', 'XP')}</div>
        </div>
      </div>
      <div className="mt-2 h-2 rounded-full bg-gray-100 overflow-hidden" role="progressbar"
           aria-valuenow={level?.progress_pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-brand-500 transition-all"
             style={{ width: `${Math.min(100, level?.progress_pct ?? 0)}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-gray-400">
        {next
          ? t(`${fmt(level.xp_to_next)} نقطة للترقية إلى «${next.title_ar}»`,
              `${fmt(level.xp_to_next)} XP to "${next.title_en}"`)
          : t('أعلى مستوى — أسطورة!', 'Top level — legend!')}
      </div>
    </div>
  )
}

function Stat({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="text-center px-2">
      <div className={`text-lg font-black ${tone}`}>{value}</div>
      <div className="text-[11px] text-gray-500 whitespace-nowrap">{label}</div>
      {sub && <div className="text-[10px] text-gray-400">{sub}</div>}
    </div>
  )
}

export default function GamificationCard({ className = '' }) {
  const navigate = useNavigate()
  const { t, lang } = useLangStore()
  const { data, isLoading, isError } = useGamificationMe()
  if (isError) return null
  if (isLoading || !data) {
    return <div className={`card h-24 animate-pulse bg-gray-50 ${className}`} />
  }
  const left = (data.open_items || []).reduce((n, i) => n + i.count, 0)
  const title = (data.titles || [])[0]            // newest title first
  const recent = title && (Date.now() - new Date(title.month).getTime()) < 62 * 864e5
  const br = data.rank?.branch
  return (
    <div className={`card ${className}`} dir={lang === 'en' ? 'ltr' : 'rtl'}>
      <div className="flex flex-wrap items-center gap-4 justify-between">
        <div className="flex-1 min-w-[220px]">
          <LevelBar level={data.level} xp={data.xp} t={t} lang={lang} />
        </div>
        <div className="flex items-center divide-x divide-gray-100 rtl:divide-x-reverse">
          <Stat label={t('نقاط اليوم', 'Today')} value={signed(data.points?.day)}
                tone={data.points?.day < 0 ? 'text-red-600' : 'text-emerald-600'} />
          <Stat label={t('هذا الشهر', 'This month')} value={signed(data.points?.month)} />
          <Stat label={t('أيام نظيفة متتالية', 'Clean-day streak')}
                value={`🔥 ${data.streak?.current ?? 0}`}
                sub={t(`الأفضل ${data.streak?.best ?? 0}`, `best ${data.streak?.best ?? 0}`)} />
          <Stat label={t('رصيد المكافآت', 'Reward balance')}
                value={`🎁 ${fmt(data.wallet?.balance)}`} />
          {br && (
            <Stat label={t('ترتيبك في الفرع', 'Branch rank')}
                  value={br.rank ? `#${br.rank}` : '—'} sub={br.of ? `/ ${br.of}` : ''} />
          )}
        </div>
        <div className="flex items-center gap-2">
          {recent && (
            <button onClick={() => navigate('/gamification?tab=champions')}
                    className="text-xs rounded-lg px-3 py-2 font-bold border border-amber-300 bg-amber-100 text-amber-900">
              {title.kind === 'network' ? ({ 1: '🥇', 2: '🥈', 3: '🥉' }[title.rank]) : '👑'}{' '}
              {title.kind === 'network'
                ? t('على منصة الشبكة', 'Network podium')
                : t('بطل الفرع', 'Branch champion')} · {String(title.month).slice(0, 7)}
            </button>
          )}
          <button
            onClick={() => navigate('/gamification?tab=me')}
            className={`text-xs rounded-lg px-3 py-2 font-bold border ${left
              ? 'border-amber-300 bg-amber-50 text-amber-800'
              : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
            {left
              ? t(`⚠️ ${left} بند ينتظرك`, `⚠️ ${left} items waiting`)
              : t('✅ لا شيء خلفك', '✅ Nothing left behind')}
          </button>
          <button onClick={() => navigate('/gamification')} className="btn-secondary text-xs">
            🏆 {t('التحفيز', 'Gamification')}
          </button>
        </div>
      </div>
    </div>
  )
}
