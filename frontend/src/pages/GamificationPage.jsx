/**
 * GamificationPage — /gamification (التحفيز: النقاط والمستويات والترتيب)
 *
 * Tabs (?tab=):
 *   me          ملفي — level ladder, open items («لا تترك شيئاً خلفك»), recent points
 *   leaderboard الترتيب — my branch (full) / network (top 10; full for managers)
 *   branches    ترتيب الفروع — average points per active player (fair to small branches)
 *   badges      الشارات
 *   rules       كيف تكسب النقاط — every rule, transparent to everyone
 *   rewards     المكافآت — spend points on the catalog (approval via /approvals)
 *   redemptions طلبات المكافآت — managers: deliver / cancel approved rewards
 *   reports     التقارير — managers (RBAC gamification/view; Excel needs /export)
 *   settings    الإعدادات — editors (gamification/edit): rules, levels, badges, manual awards
 *
 * The backend owns every number and every permission; this page only displays.
 */
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { gamificationApi, usersApi } from '../api/client'
import useLangStore from '../store/langStore'
import useHelpTab from '../help/useHelpTab'
import { PageHeader } from '../components/ui'
import { LevelBar, useGamificationMe } from '../components/GamificationCard'
import { RedemptionsTab, RewardCatalogEditor, RewardsTab } from './gamification/RewardsTabs'

const fmt = (n) => (n ?? 0).toLocaleString('en-US')
const signed = (n) => `${n > 0 ? '+' : ''}${fmt(n)}`

const PERIODS = [
  ['day', 'اليوم', 'Today'], ['week', 'الأسبوع', 'Week'], ['month', 'الشهر', 'Month'],
  ['quarter', 'الربع', 'Quarter'], ['year', 'السنة', 'Year'], ['all', 'الكل', 'All time'],
]
const ROLES = [
  ['', 'كل الأدوار', 'All roles'], ['salesperson', 'مندوب بيع', 'Salesperson'],
  ['pharmacist', 'صيدلي', 'Pharmacist'], ['call_center', 'كول سنتر', 'Call center'],
  ['delivery', 'توصيل', 'Delivery'], ['purchasing', 'مشتريات', 'Purchasing'],
  ['supervisor', 'مشرف', 'Supervisor'], ['quality_manager', 'جودة', 'Quality'],
]
const ROLE_NAMES = Object.fromEntries([...ROLES.slice(1), ['admin', 'مدير النظام', 'Admin'],
  ['viewer', 'مشاهد', 'Viewer']].map(([k, ar, en]) => [k, [ar, en]]))
export const roleLabel = (role, t) => (ROLE_NAMES[role] ? t(...ROLE_NAMES[role]) : role)

const CATEGORY = {
  sales: ['المبيعات', 'Sales'], reservations: ['الحجوزات', 'Reservations'],
  demand: ['الطلب الضائع والمتابعة', 'Demand & follow-ups'],
  transfers: ['التحويلات وطلبات الفروع', 'Transfers & branch requests'],
  inventory: ['المخزون والجرد والنواقص', 'Inventory & counts'], tasks: ['المهام', 'Tasks'],
  discipline: ['الالتزام', 'Discipline'], manual: ['تقدير يدوي', 'Manual'],
}

function Segmented({ value, onChange, options, t }) {
  return (
    <div className="inline-flex rounded-lg border border-gray-200 bg-white p-0.5 flex-wrap">
      {options.map(([k, ar, en]) => (
        <button key={k} onClick={() => onChange(k)}
                className={`px-3 py-1.5 text-xs font-bold rounded-md ${value === k
                  ? 'bg-brand-500 text-white' : 'text-gray-600 hover:bg-gray-50'}`}>
          {t(ar, en)}
        </button>
      ))}
    </div>
  )
}

function Kpi({ label, value, tone = 'text-gray-900' }) {
  return (
    <div className="card text-center py-3">
      <div className={`text-xl font-black ${tone}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  )
}

// ── ملفي ────────────────────────────────────────────────────────────────────

function MeTab({ me, t, lang }) {
  const navigate = useNavigate()
  const { data: levels = [] } = useQuery({
    queryKey: ['gamificationLevels'], queryFn: () => gamificationApi.levels().then(r => r.data),
  })
  const open = me.open_items || []
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card lg:col-span-2">
          <LevelBar level={me.level} xp={me.xp} t={t} lang={lang} />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
            <Kpi label={t('نقاط اليوم', 'Today')} value={signed(me.points?.day)}
                 tone={me.points?.day < 0 ? 'text-red-600' : 'text-emerald-600'} />
            <Kpi label={t('هذا الأسبوع', 'This week')} value={signed(me.points?.week)} />
            <Kpi label={t('هذا الشهر', 'This month')} value={signed(me.points?.month)} />
            <Kpi label={t('أيام نظيفة متتالية', 'Clean-day streak')}
                 value={`🔥 ${me.streak?.current ?? 0}`} />
          </div>
          <div className="grid grid-cols-2 gap-3 mt-3 text-sm">
            <div className="rounded-lg bg-gray-50 p-3">
              <div className="text-xs text-gray-500">{t('ترتيبك في الفرع (الشهر)', 'Branch rank (month)')}</div>
              <div className="font-black text-gray-900">
                {me.rank?.branch?.rank ? `#${me.rank.branch.rank} / ${me.rank.branch.of}` : '—'}
              </div>
            </div>
            <div className="rounded-lg bg-gray-50 p-3">
              <div className="text-xs text-gray-500">
                {t(`ترتيبك على الشبكة بين «${roleLabel(me.role, t)}»`, `Network rank among ${roleLabel(me.role, t)}`)}
              </div>
              <div className="font-black text-gray-900">
                {me.rank?.network_role?.rank ? `#${me.rank.network_role.rank} / ${me.rank.network_role.of}` : '—'}
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="font-black text-gray-900 mb-2">
            {t('🧹 لا تترك شيئاً خلفك', '🧹 Leave nothing behind')}
          </div>
          {open.length === 0 ? (
            <div className="text-sm text-emerald-700 bg-emerald-50 rounded-lg p-3">
              {t('ممتاز — لا يوجد ما ينتظرك الآن. أكمل اليوم هكذا لتكسب «يوم نظيف».',
                 'Great — nothing is waiting. Finish the day like this to earn a "clean day".')}
            </div>
          ) : (
            <ul className="space-y-2">
              {open.map(i => (
                <li key={i.key}>
                  <button onClick={() => navigate(i.route)}
                          className={`w-full flex items-center justify-between rounded-lg px-3 py-2 text-sm border ${i.penalty
                            ? 'border-red-200 bg-red-50 text-red-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
                    <span className="text-start">{lang === 'en' ? i.label_en : i.label_ar}</span>
                    <span className="font-black">{i.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="text-[11px] text-gray-400 mt-2">
            {t('البنود الحمراء تخصم نقاطاً عند إغلاق اليوم.', 'Red items deduct points at day close.')}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <div className="font-black text-gray-900 mb-3">{t('🪜 سلّم المستويات', '🪜 Level ladder')}</div>
          <ol className="space-y-1.5">
            {levels.map(lv => {
              const reached = (me.level?.current?.number ?? 1) >= lv.number
              return (
                <li key={lv.number}
                    className={`flex items-center justify-between rounded-lg px-3 py-1.5 text-sm ${reached
                      ? 'bg-brand-50 text-gray-900' : 'text-gray-400'}`}>
                  <span>{lv.icon} {lv.number}. {lang === 'en' ? lv.title_en : lv.title_ar}</span>
                  <span className="text-xs">{fmt(lv.min_xp)} {t('نقطة', 'XP')}</span>
                </li>
              )
            })}
          </ol>
        </div>
        <div className="card">
          <div className="font-black text-gray-900 mb-3">{t('🕒 آخر النقاط', '🕒 Recent points')}</div>
          {(me.recent || []).length === 0 ? (
            <p className="text-sm text-gray-400">{t('لا توجد نقاط بعد.', 'No points yet.')}</p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {me.recent.map(e => (
                <li key={e.id} className="flex items-center justify-between py-1.5 text-sm">
                  <span className="min-w-0 truncate">
                    {lang === 'en' ? e.name_en : e.name_ar}
                    {e.reason && <span className="text-xs text-gray-400"> — {e.reason}</span>}
                    <span className="text-xs text-gray-400 mx-1">{e.day}</span>
                  </span>
                  <span className={`font-black ${e.points < 0 ? 'text-red-600' : 'text-emerald-600'}`}>
                    {signed(e.points)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {(me.categories || []).length > 0 && (
        <div className="card">
          <div className="font-black text-gray-900 mb-3">{t('نقاط الشهر حسب نوع العمل', 'This month by kind of work')}</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {me.categories.map(c => (
              <div key={c.key} className="rounded-lg bg-gray-50 p-2 text-sm flex justify-between">
                <span>{t(...(CATEGORY[c.key] || [c.key, c.key]))}</span>
                <b className={c.points < 0 ? 'text-red-600' : ''}>{signed(c.points)}</b>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── الترتيب ──────────────────────────────────────────────────────────────────

export function LeaderboardTable({ rows, meId, t, lang, compact = false }) {
  if (!rows?.length) {
    return <p className="text-sm text-gray-400 p-4">{t('لا توجد نقاط في هذه الفترة.', 'No points in this period.')}</p>
  }
  const medal = (r) => ({ 1: '🥇', 2: '🥈', 3: '🥉' }[r] || r)
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-xs text-gray-500 border-b border-gray-100">
          <tr>
            <th className="py-2 px-2 text-start">#</th>
            <th className="py-2 px-2 text-start">{t('الموظف', 'Employee')}</th>
            {!compact && <th className="py-2 px-2 text-start">{t('الفرع', 'Branch')}</th>}
            <th className="py-2 px-2 text-start">{t('المستوى', 'Level')}</th>
            <th className="py-2 px-2 text-end">{t('النقاط', 'Points')}</th>
            {!compact && <th className="py-2 px-2 text-end">{t('الخصومات', 'Deductions')}</th>}
            {!compact && <th className="py-2 px-2 text-end">🔥</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.staff_id} className={`border-b border-gray-50 ${r.staff_id === meId ? 'bg-brand-50 font-bold' : ''}`}>
              <td className="py-1.5 px-2">{medal(r.rank)}</td>
              <td className="py-1.5 px-2">
                {r.name}<div className="text-[11px] text-gray-400">{roleLabel(r.role, t)}</div>
              </td>
              {!compact && <td className="py-1.5 px-2 text-gray-500">{r.branch}</td>}
              <td className="py-1.5 px-2 whitespace-nowrap">
                {r.level ? `${r.level.icon} ${lang === 'en' ? r.level.title_en : r.level.title_ar}` : '—'}
              </td>
              <td className="py-1.5 px-2 text-end font-black">{fmt(r.net)}</td>
              {!compact && <td className="py-1.5 px-2 text-end text-red-600">{r.lost ? fmt(r.lost) : ''}</td>}
              {!compact && <td className="py-1.5 px-2 text-end">{r.streak || ''}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LeaderboardTab({ me, t, lang }) {
  const [period, setPeriod] = useState('month')
  const [scope, setScope] = useState('branch')
  const [role, setRole] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['gamificationBoard', period, scope, role],
    queryFn: () => gamificationApi.leaderboard({ period, scope, role: role || undefined }).then(r => r.data),
  })
  return (
    <div className="card space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <Segmented value={scope} onChange={setScope} t={t}
                   options={[['branch', 'فرعي', 'My branch'], ['network', 'كل الفروع', 'Network']]} />
        <Segmented value={period} onChange={setPeriod} options={PERIODS} t={t} />
        <select value={role} onChange={e => setRole(e.target.value)} className="input-field text-xs w-auto">
          {ROLES.map(([k, ar, en]) => <option key={k} value={k}>{t(ar, en)}</option>)}
        </select>
      </div>
      {data?.limited && (
        <p className="text-xs text-gray-500">
          {t('يظهر أفضل 10 على الشبكة.', 'Showing the network top 10.')}
          {data.me?.rank && t(` ترتيبك: #${data.me.rank}`, ` Your rank: #${data.me.rank}`)}
        </p>
      )}
      {isLoading ? <div className="h-40 animate-pulse bg-gray-50 rounded-lg" />
        : <LeaderboardTable rows={data?.rows} meId={me.staff_id} t={t} lang={lang} />}
    </div>
  )
}

function BranchesTab({ t }) {
  const [period, setPeriod] = useState('month')
  const { data } = useQuery({
    queryKey: ['gamificationBranches', period],
    queryFn: () => gamificationApi.branches({ period }).then(r => r.data),
  })
  return (
    <div className="card space-y-3">
      <Segmented value={period} onChange={setPeriod} options={PERIODS} t={t} />
      <p className="text-xs text-gray-500">
        {t('الترتيب بمتوسط نقاط اللاعب النشط — عادل بين الفروع الكبيرة والصغيرة.',
           'Ranked by average points per active player — fair to big and small branches.')}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-gray-500 border-b border-gray-100">
            <tr>
              <th className="py-2 px-2 text-start">#</th>
              <th className="py-2 px-2 text-start">{t('الفرع', 'Branch')}</th>
              <th className="py-2 px-2 text-end">{t('متوسط اللاعب', 'Avg / player')}</th>
              <th className="py-2 px-2 text-end">{t('إجمالي النقاط', 'Total')}</th>
              <th className="py-2 px-2 text-end">{t('اللاعبون', 'Players')}</th>
              <th className="py-2 px-2 text-end">{t('أيام نظيفة %', 'Clean days %')}</th>
              <th className="py-2 px-2 text-end">{t('بنود متأخرة', 'Left behind')}</th>
            </tr>
          </thead>
          <tbody>
            {(data?.rows || []).map(r => (
              <tr key={r.branch_id} className="border-b border-gray-50">
                <td className="py-1.5 px-2">{({ 1: '🥇', 2: '🥈', 3: '🥉' }[r.rank]) || r.rank}</td>
                <td className="py-1.5 px-2">{r.branch}</td>
                <td className="py-1.5 px-2 text-end font-black">{fmt(r.avg_per_player)}</td>
                <td className="py-1.5 px-2 text-end">{fmt(r.net)}</td>
                <td className="py-1.5 px-2 text-end">{r.players}</td>
                <td className="py-1.5 px-2 text-end">{r.clean_day_rate ?? '—'}</td>
                <td className="py-1.5 px-2 text-end text-amber-700">{r.left_behind || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function BadgesTab({ me, t, lang }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      {(me.badges || []).map(b => (
        <div key={b.key} className={`card text-center ${b.earned ? '' : 'opacity-60'}`}>
          <div className={`text-4xl ${b.earned ? '' : 'grayscale'}`}>{b.icon}</div>
          <div className="font-black text-gray-900 mt-1">{lang === 'en' ? b.name_en : b.name_ar}</div>
          <div className="text-xs text-gray-500">{lang === 'en' ? b.desc_en : b.desc_ar}</div>
          {b.earned ? (
            <div className="text-xs text-emerald-700 mt-2">✅ {t('مكتسبة', 'Earned')}</div>
          ) : (
            <div className="mt-2">
              <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                <div className="h-full bg-brand-500" style={{ width: `${(b.progress / b.threshold) * 100}%` }} />
              </div>
              <div className="text-[11px] text-gray-400 mt-1">{fmt(b.progress)} / {fmt(b.threshold)}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function RuleText({ r, t }) {
  const parts = []
  if (r.unit_value) parts.push(t(`لكل ${fmt(r.unit_value)} جنيه`, `per ${fmt(r.unit_value)} EGP`))
  if (r.cash_multiplier && r.cash_multiplier !== 1) parts.push(t(`الكاش ×${r.cash_multiplier}`, `cash ×${r.cash_multiplier}`))
  if (r.daily_cap != null) parts.push(t(`حد يومي ${r.daily_cap}`, `daily cap ${r.daily_cap}`))
  return parts.length ? <span className="text-[11px] text-gray-400"> · {parts.join(' · ')}</span> : null
}

function RulesTab({ t, lang }) {
  const { data: rules = [] } = useQuery({
    queryKey: ['gamificationRules'], queryFn: () => gamificationApi.rules().then(r => r.data),
  })
  const groups = useMemo(() => {
    const g = {}
    rules.filter(r => r.is_active && r.key !== 'manual_award').forEach(r => { (g[r.category] ||= []).push(r) })
    return g
  }, [rules])
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {Object.entries(groups).map(([cat, list]) => (
        <div key={cat} className="card">
          <div className="font-black text-gray-900 mb-2">{t(...(CATEGORY[cat] || [cat, cat]))}</div>
          <ul className="divide-y divide-gray-100">
            {list.map(r => (
              <li key={r.key} className="py-1.5 flex items-start justify-between gap-3 text-sm">
                <span>
                  {lang === 'en' ? r.name_en : r.name_ar}
                  <div className="text-xs text-gray-500">{lang === 'en' ? r.desc_en : r.desc_ar}<RuleText r={r} t={t} /></div>
                </span>
                <b className={r.points < 0 ? 'text-red-600' : 'text-emerald-600'}>{signed(r.points)}</b>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

// ── التقارير (managers) ──────────────────────────────────────────────────────

function ReportsTab({ t, lang }) {
  const [period, setPeriod] = useState('month')
  const [err, setErr] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['gamificationReport', period],
    queryFn: () => gamificationApi.report({ period }).then(r => r.data),
  })
  const download = async () => {
    setErr('')
    try {
      const r = await gamificationApi.exportReport({ period })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `gamification_${period}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setErr(t('ليس لديك صلاحية التصدير.', 'You are not allowed to export.'))
    }
  }
  if (isLoading || !data) return <div className="h-60 animate-pulse bg-gray-50 rounded-lg" />
  const k = data.kpis
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <Segmented value={period} onChange={setPeriod} options={PERIODS} t={t} />
        <div className="flex items-center gap-2">
          {err && <span className="text-xs text-red-600">{err}</span>}
          <button onClick={download} className="btn-secondary text-xs">⬇️ {t('تصدير Excel', 'Export Excel')}</button>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <Kpi label={t('موظفون مشاركون', 'Active players')} value={fmt(k.players)} />
        <Kpi label={t('نقاط مكتسبة', 'Points earned')} value={fmt(k.earned)} tone="text-emerald-600" />
        <Kpi label={t('خصومات', 'Deductions')} value={fmt(k.lost)} tone="text-red-600" />
        <Kpi label={t('أيام نظيفة %', 'Clean days %')} value={k.clean_day_rate ?? '—'} />
        <Kpi label={t('بنود تُركت متأخرة', 'Items left behind')} value={fmt(k.left_behind)} tone="text-amber-700" />
        <Kpi label={t('ترقيات', 'Promotions')} value={fmt(k.promotions)} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <div className="font-black mb-2">{t('🏆 الأفضل أداءً', '🏆 Top performers')}</div>
          <LeaderboardTable rows={data.top} t={t} lang={lang} compact />
        </div>
        <div className="card">
          <div className="font-black mb-2">{t('🔻 يحتاجون دعماً', '🔻 Need support')}</div>
          <LeaderboardTable rows={data.bottom} t={t} lang={lang} compact />
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <div className="font-black mb-2">{t('النقاط حسب نوع العمل', 'Points by kind of work')}</div>
          <table className="w-full text-sm">
            <tbody>
              {data.categories.map(c => (
                <tr key={c.key} className="border-b border-gray-50">
                  <td className="py-1.5">{t(...(CATEGORY[c.key] || [c.key, c.key]))}</td>
                  <td className="py-1.5 text-end text-emerald-600">{fmt(c.earned)}</td>
                  <td className="py-1.5 text-end text-red-600">{c.lost ? fmt(c.lost) : ''}</td>
                  <td className="py-1.5 text-end text-gray-400">{fmt(c.events)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="font-black mb-2">{t('توزيع المستويات', 'Level distribution')}</div>
          <ul className="space-y-1">
            {data.levels.map(l => (
              <li key={l.level.number} className="flex items-center gap-2 text-sm">
                <span className="w-36 truncate">{l.level.icon} {lang === 'en' ? l.level.title_en : l.level.title_ar}</span>
                <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
                  <div className="h-full bg-brand-500"
                       style={{ width: `${k.players ? Math.min(100, (l.players / Math.max(...data.levels.map(x => x.players), 1)) * 100) : 0}%` }} />
                </div>
                <span className="w-10 text-end font-bold">{l.players}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {data.branches?.length > 0 && (
        <div className="card">
          <div className="font-black mb-2">{t('الفروع', 'Branches')}</div>
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 border-b border-gray-100">
              <tr>
                <th className="py-2 text-start">{t('الفرع', 'Branch')}</th>
                <th className="py-2 text-end">{t('متوسط اللاعب', 'Avg / player')}</th>
                <th className="py-2 text-end">{t('أيام نظيفة %', 'Clean %')}</th>
                <th className="py-2 text-end">{t('بنود متأخرة', 'Left behind')}</th>
              </tr>
            </thead>
            <tbody>
              {data.branches.map(b => (
                <tr key={b.branch_id} className="border-b border-gray-50">
                  <td className="py-1.5">{b.rank}. {b.branch}</td>
                  <td className="py-1.5 text-end font-bold">{fmt(b.avg_per_player)}</td>
                  <td className="py-1.5 text-end">{b.clean_day_rate ?? '—'}</td>
                  <td className="py-1.5 text-end">{b.left_behind || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.rewards && (
        <div className="card">
          <div className="font-black mb-2">{t('🎁 المكافآت في الفترة', '🎁 Rewards in the period')}</div>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <Kpi label={t('طلبات', 'Requests')} value={fmt(data.rewards.requests)} />
            <Kpi label={t('نقاط مستبدلة', 'Points redeemed')} value={fmt(data.rewards.points_redeemed)} />
            <Kpi label={t('بانتظار التسليم', 'To deliver')} value={fmt(data.rewards.awaiting_fulfilment)} tone="text-amber-700" />
          </div>
          <ul className="divide-y divide-gray-100 text-sm">
            {data.rewards.top.map(r => (
              <li key={r.reward_id} className="py-1.5 flex justify-between">
                <span>{r.icon} {lang === 'en' ? r.name_en : r.name_ar}</span>
                <span className="text-gray-500">{fmt(r.requests)} · {fmt(r.points)} {t('نقطة', 'pts')}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.promotions?.length > 0 && (
        <div className="card">
          <div className="font-black mb-2">{t('🎉 الترقيات في الفترة', '🎉 Promotions in the period')}</div>
          <ul className="divide-y divide-gray-100 text-sm">
            {data.promotions.map((p, i) => (
              <li key={i} className="py-1.5 flex justify-between">
                <span>{p.name} <span className="text-xs text-gray-400">{p.branch}</span></span>
                <span>{p.level.icon} {lang === 'en' ? p.level.title_en : p.level.title_ar}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── الإعدادات (editors) ──────────────────────────────────────────────────────

function RuleRow({ r, t, lang, onSave }) {
  const [d, setD] = useState({ points: r.points, daily_cap: r.daily_cap ?? '', is_active: r.is_active })
  const dirty = d.points !== r.points || String(d.daily_cap) !== String(r.daily_cap ?? '') || d.is_active !== r.is_active
  return (
    <tr className="border-b border-gray-50">
      <td className="py-1.5">{lang === 'en' ? r.name_en : r.name_ar}<div className="text-[11px] text-gray-400">{r.key}</div></td>
      <td className="py-1.5"><input type="number" className="input-field w-20 text-xs" value={d.points}
                                    onChange={e => setD({ ...d, points: Number(e.target.value) })} /></td>
      <td className="py-1.5"><input type="number" className="input-field w-20 text-xs" value={d.daily_cap}
                                    placeholder={t('بلا حد', 'none')}
                                    onChange={e => setD({ ...d, daily_cap: e.target.value })} /></td>
      <td className="py-1.5 text-center"><input type="checkbox" checked={d.is_active}
                                                onChange={e => setD({ ...d, is_active: e.target.checked })} /></td>
      <td className="py-1.5">
        {dirty && (
          <button className="btn-primary text-xs"
                  onClick={() => onSave(r.key, { points: d.points, is_active: d.is_active,
                                                 daily_cap: d.daily_cap === '' ? null : Number(d.daily_cap) })}>
            {t('حفظ', 'Save')}
          </button>
        )}
      </td>
    </tr>
  )
}

function SettingsTab({ t, lang }) {
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')
  const [adj, setAdj] = useState({ staff_id: '', points: '', reason: '' })
  const [q, setQ] = useState('')
  const { data: rules = [] } = useQuery({
    queryKey: ['gamificationRules'], queryFn: () => gamificationApi.rules().then(r => r.data),
  })
  const { data: levels = [] } = useQuery({
    queryKey: ['gamificationLevels'], queryFn: () => gamificationApi.levels().then(r => r.data),
  })
  const { data: staff = [] } = useQuery({
    queryKey: ['gamificationStaffSearch', q],
    queryFn: () => usersApi.list({ search: q }).then(r => r.data?.results || r.data || []),
    enabled: q.length >= 2,
  })
  const { data: changes = [] } = useQuery({
    queryKey: ['gamificationChanges'], queryFn: () => gamificationApi.changes().then(r => r.data),
  })
  const show = (m) => { setMsg(m); setTimeout(() => setMsg(''), 4000) }
  const errText = (e) => Object.values(e?.response?.data || {}).join(' · ') || t('حدث خطأ', 'Error')
  const saveRule = useMutation({
    mutationFn: ({ key, data }) => gamificationApi.updateRule(key, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['gamificationRules'] }); qc.invalidateQueries({ queryKey: ['gamificationChanges'] }); show(t('تم الحفظ', 'Saved')) },
    onError: (e) => show(errText(e)),
  })
  const saveLevel = useMutation({
    mutationFn: ({ n, data }) => gamificationApi.updateLevel(n, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['gamificationLevels'] }); show(t('تم الحفظ', 'Saved')) },
    onError: (e) => show(errText(e)),
  })
  const award = useMutation({
    mutationFn: () => gamificationApi.adjust({ ...adj, points: Number(adj.points) }),
    onSuccess: () => { setAdj({ staff_id: '', points: '', reason: '' }); setQ(''); qc.invalidateQueries({ queryKey: ['gamificationChanges'] }); show(t('تم تسجيل التقدير', 'Recorded')) },
    onError: (e) => show(errText(e)),
  })
  const runNow = useMutation({
    mutationFn: () => gamificationApi.run({ days: 1 }),
    onSuccess: (r) => show(t(`تم الاحتساب: ${r.data.awarded} حركة`, `Done: ${r.data.awarded} events`)),
    onError: (e) => show(errText(e)),
  })
  return (
    <div className="space-y-4">
      {msg && <div className="rounded-lg bg-gray-900 text-white text-sm px-3 py-2">{msg}</div>}

      <RewardCatalogEditor t={t} lang={lang} />

      <div className="card">
        <div className="flex items-center justify-between mb-2">
          <div className="font-black">{t('قواعد النقاط', 'Point rules')}</div>
          <button className="btn-secondary text-xs" onClick={() => runNow.mutate()} disabled={runNow.isPending}>
            🔄 {t('إعادة الاحتساب الآن', 'Recalculate now')}
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 border-b border-gray-100">
              <tr>
                <th className="py-2 text-start">{t('القاعدة', 'Rule')}</th>
                <th className="py-2 text-start">{t('النقاط', 'Points')}</th>
                <th className="py-2 text-start">{t('الحد اليومي', 'Daily cap')}</th>
                <th className="py-2">{t('مفعّلة', 'Active')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.map(r => <RuleRow key={`${r.key}-${r.points}-${r.daily_cap}-${r.is_active}`} r={r} t={t} lang={lang}
                                       onSave={(key, data) => saveRule.mutate({ key, data })} />)}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <div className="font-black mb-2">{t('المستويات والألقاب', 'Levels and titles')}</div>
          <ul className="space-y-1.5">
            {levels.map(lv => (
              <LevelRow key={`${lv.number}-${lv.min_xp}-${lv.title_ar}-${lv.title_en}`} lv={lv} t={t}
                        onSave={(data) => saveLevel.mutate({ n: lv.number, data })} />
            ))}
          </ul>
        </div>

        <div className="card space-y-2">
          <div className="font-black">{t('تقدير يدوي (منح أو خصم)', 'Manual recognition (+/−)')}</div>
          <input className="input-field text-sm" placeholder={t('ابحث عن موظف…', 'Search employee…')}
                 value={q} onChange={e => setQ(e.target.value)} />
          {q.length >= 2 && (
            <select className="input-field text-sm" value={adj.staff_id} onChange={e => setAdj({ ...adj, staff_id: e.target.value })}>
              <option value="">{t('— اختر —', '— choose —')}</option>
              {staff.map(s => <option key={s.id} value={s.id}>{s.full_name || s.username} {s.branch_name ? `· ${s.branch_name}` : ''}</option>)}
            </select>
          )}
          <input type="number" className="input-field text-sm" placeholder={t('النقاط (سالب للخصم)', 'Points (negative to deduct)')}
                 value={adj.points} onChange={e => setAdj({ ...adj, points: e.target.value })} />
          <input className="input-field text-sm" placeholder={t('السبب (إلزامي)', 'Reason (required)')}
                 value={adj.reason} onChange={e => setAdj({ ...adj, reason: e.target.value })} />
          <button className="btn-primary text-sm w-full" disabled={!adj.staff_id || !adj.points || award.isPending}
                  onClick={() => award.mutate()}>
            {t('تسجيل', 'Record')}
          </button>
          <p className="text-[11px] text-gray-400">
            {t('كل تقدير يُسجَّل باسمك وسببه في سجل التعديلات.', 'Every award is logged with your name and reason.')}
          </p>
        </div>
      </div>

      <div className="card">
        <div className="font-black mb-2">{t('سجل التعديلات', 'Change log')}</div>
        <ul className="divide-y divide-gray-100 text-xs max-h-72 overflow-y-auto">
          {changes.map(c => (
            <li key={c.id} className="py-1.5 flex justify-between gap-2">
              <span>{c.actor} · {c.action} · {c.target}{c.reason ? ` — ${c.reason}` : ''}</span>
              <span className="text-gray-400 whitespace-nowrap">{String(c.created_at).slice(0, 16).replace('T', ' ')}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function LevelRow({ lv, t, onSave }) {
  const [d, setD] = useState({ min_xp: lv.min_xp, title_ar: lv.title_ar, title_en: lv.title_en })
  const dirty = d.min_xp !== lv.min_xp || d.title_ar !== lv.title_ar || d.title_en !== lv.title_en
  return (
    <li className="flex items-center gap-1.5 text-sm">
      <span className="w-8">{lv.icon}{lv.number}</span>
      <input className="input-field text-xs flex-1" value={d.title_ar} onChange={e => setD({ ...d, title_ar: e.target.value })} />
      <input className="input-field text-xs flex-1" dir="ltr" value={d.title_en} onChange={e => setD({ ...d, title_en: e.target.value })} />
      <input type="number" className="input-field text-xs w-24" value={d.min_xp} disabled={lv.number === 1}
             onChange={e => setD({ ...d, min_xp: Number(e.target.value) })} />
      {dirty && <button className="btn-primary text-xs" onClick={() => onSave(d)}>{t('حفظ', 'Save')}</button>}
    </li>
  )
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function GamificationPage() {
  const { t, lang } = useLangStore()
  const [params, setParams] = useSearchParams()
  const { data: me, isLoading, isError } = useGamificationMe()
  const tabs = [
    ['me', '🙋 ملفي', '🙋 My profile'],
    ['leaderboard', '🏆 الترتيب', '🏆 Leaderboard'],
    ['branches', '🏢 ترتيب الفروع', '🏢 Branches'],
    ['badges', '🏅 الشارات', '🏅 Badges'],
    ['rules', '📜 كيف تكسب النقاط', '📜 How to earn'],
    ['rewards', '🎁 المكافآت', '🎁 Rewards'],
    ...(me?.can_manage ? [['redemptions', '📦 طلبات المكافآت', '📦 Reward requests'],
                          ['reports', '📊 التقارير', '📊 Reports']] : []),
    ...(me?.can_edit ? [['settings', '⚙️ الإعدادات', '⚙️ Settings']] : []),
  ]
  const requested = params.get('tab') || 'me'
  const tab = tabs.some(([k]) => k === requested) ? requested : 'me'
  useHelpTab(tab)
  const setTab = (k) => setParams({ tab: k }, { replace: true })

  return (
    <div className="pb-20" dir={lang === 'en' ? 'ltr' : 'rtl'}>
      <PageHeader title={t('التحفيز — النقاط والمستويات', 'Gamification — points & levels')}
                  subtitle={t('كل عمل تنجزه يُحتسب: ارتقِ في المستويات، اجمع الشارات، ولا تترك شيئاً خلفك',
                              'Every job you do counts: climb levels, collect badges, and leave nothing behind')} />
      <div className="px-4 sm:px-6 space-y-4">
        <div className="flex gap-1 overflow-x-auto border-b border-gray-200">
          {tabs.map(([k, ar, en]) => (
            <button key={k} onClick={() => setTab(k)}
                    className={`px-3 py-2 text-sm font-bold whitespace-nowrap border-b-2 -mb-px ${tab === k
                      ? 'border-brand-500 text-brand-700' : 'border-transparent text-gray-500 hover:text-gray-800'}`}>
              {t(ar, en)}
            </button>
          ))}
        </div>
        {isError && <div className="card text-sm text-red-600">{t('تعذر تحميل البيانات.', 'Could not load data.')}</div>}
        {isLoading || !me ? <div className="h-60 animate-pulse bg-gray-50 rounded-lg" /> : (
          <>
            {tab === 'me' && <MeTab me={me} t={t} lang={lang} />}
            {tab === 'leaderboard' && <LeaderboardTab me={me} t={t} lang={lang} />}
            {tab === 'branches' && <BranchesTab t={t} />}
            {tab === 'badges' && <BadgesTab me={me} t={t} lang={lang} />}
            {tab === 'rules' && <RulesTab t={t} lang={lang} />}
            {tab === 'rewards' && <RewardsTab t={t} lang={lang} />}
            {tab === 'redemptions' && me.can_manage && <RedemptionsTab t={t} lang={lang} canEdit={me.can_edit} />}
            {tab === 'reports' && me.can_manage && <ReportsTab t={t} lang={lang} />}
            {tab === 'settings' && me.can_edit && <SettingsTab t={t} lang={lang} />}
          </>
        )}
      </div>
    </div>
  )
}
