/**
 * ChallengesTab — /gamification?tab=challenges (🤝 تحديات الفروع).
 *   • Every running / upcoming / recently ended challenge: goal, period, bonus per member,
 *     my branch's progress and every branch's standing (network-wide, like the branch ranking).
 *   • Editors (gamification/edit): create a challenge inline, switch one off, judge an
 *     ended one now (normally automatic at the nightly day close).
 * The server computes every value and decides who met the goal; this only displays.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi, gamificationApi } from '../../api/client'

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 }))

const METRIC_TEXT = {
  left_behind_max:  ['لا شيء متأخر', 'Nothing left behind', 'بنود متأخرة على الأكثر', 'items left behind at most'],
  clean_day_rate:   ['أيام نظيفة', 'Clean days', '% أيام نظيفة على الأقل', '% clean days at least'],
  fast_reply_rate:  ['رد سريع على الفروع', 'Fast replies to branches', '% من طلبات الفروع خلال المهلة على الأقل', '% of branch requests answered in time at least'],
  daily_count_rate: ['إنجاز الجرد اليومي', 'Daily count done', '% من أصناف الجرد اليومي على الأقل', '% of daily-count items at least'],
  avg_points:       ['متوسط النقاط', 'Average points', 'نقطة لكل موظف على الأقل', 'points per employee at least'],
}
const metricName = (m, t) => t(...(METRIC_TEXT[m] || [m, m]).slice(0, 2))
const goalText = (c, t) => {
  const x = METRIC_TEXT[c.metric] || ['', '', '', '']
  return `${fmt(c.target)} ${t(x[2], x[3])}`
}

function progressPct(c, value) {
  if (value == null) return 0
  if (c.lower_is_better) return value <= c.target ? 100 : Math.max(5, 100 - (value - c.target) * 10)
  return c.target ? Math.min(100, (value / c.target) * 100) : 100
}

function StatusChip({ row, c, t }) {
  if (!row) return <span className="text-[11px] text-gray-400">{t('فرعك ليس ضمن التحدي', 'Your branch is not in this challenge')}</span>
  if (row.value == null) return <span className="text-[11px] rounded-full px-2 py-0.5 bg-gray-100 text-gray-500">{t('لا بيانات بعد', 'No data yet')}</span>
  if (row.final) {
    return row.achieved
      ? <span className="text-[11px] rounded-full px-2 py-0.5 bg-emerald-50 text-emerald-700 font-bold">✅ {t(`تحقق — +${row.bonus} لكل عضو`, `Met — +${row.bonus} each`)}</span>
      : <span className="text-[11px] rounded-full px-2 py-0.5 bg-red-50 text-red-700">{t('لم يتحقق', 'Not met')}</span>
  }
  return row.achieved
    ? <span className="text-[11px] rounded-full px-2 py-0.5 bg-emerald-50 text-emerald-700">{t('على الطريق الصحيح', 'On track')}</span>
    : <span className="text-[11px] rounded-full px-2 py-0.5 bg-amber-50 text-amber-800">{t('لم يصل للهدف بعد', 'Below the goal so far')}</span>
}

function ChallengeCard({ c, t, lang, canEdit, onToggle, onEvaluate, busy, myBranchId }) {
  const [open, setOpen] = useState(false)
  const today = new Date().toISOString().slice(0, 10)
  const state = c.evaluated_at ? 'done' : (c.start > today ? 'upcoming' : (c.end < today ? 'ended' : 'running'))
  const mine = c.mine
  return (
    <div className={`card space-y-2 ${c.is_active ? '' : 'opacity-60'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <span className="text-2xl">{c.icon}</span>
          <div className="min-w-0">
            <div className="font-black text-gray-900">{lang === 'en' ? c.name_en : c.name_ar}</div>
            <div className="text-xs text-gray-500">{lang === 'en' ? c.desc_en : c.desc_ar}</div>
            <div className="text-[11px] text-gray-400 mt-0.5">
              {metricName(c.metric, t)} · {t('الهدف', 'Goal')}: {goalText(c, t)} · {c.start} → {c.end}
              {' · '}{t(`+${c.bonus_per_member} نقطة لكل عضو`, `+${c.bonus_per_member} points per member`)}
            </div>
          </div>
        </div>
        <span className="text-[11px] font-bold rounded-full px-2 py-0.5 bg-gray-100 text-gray-600">
          {{ running: t('جارٍ', 'Running'), upcoming: t('قادم', 'Upcoming'),
             ended: t('انتهى — يُقيَّم الليلة', 'Ended — judged tonight'), done: t('تم التقييم', 'Judged') }[state]}
        </span>
      </div>
      {state !== 'upcoming' && (
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span>{t('فرعك', 'Your branch')}: <b>{fmt(mine?.value)}</b></span>
            <StatusChip row={mine} c={c} t={t} />
          </div>
          <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
            <div className={`h-full ${mine?.achieved ? 'bg-emerald-500' : 'bg-brand-500'}`}
                 style={{ width: `${progressPct(c, mine?.value)}%` }} />
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {c.standings?.length > 0 && (
          <button className="text-xs text-brand-700 underline" onClick={() => setOpen(o => !o)}>
            {open ? t('إخفاء الفروع', 'Hide branches') : t(`كل الفروع (${c.standings.length})`, `All branches (${c.standings.length})`)}
          </button>
        )}
        {canEdit && !c.evaluated_at && (
          <>
            <button className="text-xs text-gray-500 underline" disabled={busy} onClick={() => onToggle(c)}>
              {c.is_active ? t('إيقاف', 'Switch off') : t('تفعيل', 'Switch on')}
            </button>
            {state === 'ended' && (
              <button className="btn-secondary text-xs" disabled={busy} onClick={() => onEvaluate(c)}>
                {t('قيِّم الآن', 'Judge now')}
              </button>
            )}
          </>
        )}
      </div>
      {open && (
        <table className="w-full text-sm">
          <tbody>
            {c.standings.map((r, i) => (
              <tr key={r.branch_id} className={`border-b border-gray-50 ${r.branch_id === myBranchId ? 'bg-brand-50 font-bold' : ''}`}>
                <td className="py-1">{i + 1}. {r.branch}</td>
                <td className="py-1 text-end">{fmt(r.value)}</td>
                <td className="py-1 text-end">{r.achieved ? '✅' : (r.value == null ? '—' : '')}</td>
                <td className="py-1 text-end text-xs text-gray-400">{t(`${r.members} موظف`, `${r.members} staff`)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

const EMPTY = { name_ar: '', name_en: '', desc_ar: '', desc_en: '', icon: '🤝', metric: 'left_behind_max',
                target: '', start: '', end: '', bonus_per_member: 100, min_members: 2, branch_ids: [] }

function NewChallengeForm({ t, lang, onSave, onCancel, busy }) {
  const [d, setD] = useState(EMPTY)
  const set = (k) => (e) => setD({ ...d, [k]: e.target.value })
  const { data: branches = [] } = useQuery({
    queryKey: ['branchesForChallenge'],
    queryFn: () => branchesApi.list().then(r => r.data?.results || r.data || []),
  })
  const toggleBranch = (id) => setD({ ...d, branch_ids: d.branch_ids.includes(id)
    ? d.branch_ids.filter(x => x !== id) : [...d.branch_ids, id] })
  return (
    <div className="card space-y-2 bg-gray-50">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <input className="input-field text-sm" placeholder={t('الاسم بالعربي', 'Arabic name')} value={d.name_ar} onChange={set('name_ar')} />
        <input className="input-field text-sm" dir="ltr" placeholder="English name" value={d.name_en} onChange={set('name_en')} />
        <input className="input-field text-sm" placeholder={t('الشرح بالعربي (اختياري)', 'Arabic description (optional)')} value={d.desc_ar} onChange={set('desc_ar')} />
        <input className="input-field text-sm" dir="ltr" placeholder="English description (optional)" value={d.desc_en} onChange={set('desc_en')} />
        <select className="input-field text-sm" value={d.metric} onChange={set('metric')}>
          {Object.keys(METRIC_TEXT).map(k => <option key={k} value={k}>{metricName(k, t)}</option>)}
        </select>
        <label className="text-xs flex items-center gap-2">
          <input type="number" className="input-field text-sm w-28" value={d.target} onChange={set('target')} />
          {t(METRIC_TEXT[d.metric][2], METRIC_TEXT[d.metric][3])}
        </label>
        <label className="text-xs flex items-center gap-2">{t('من', 'From')}
          <input type="date" className="input-field text-sm" value={d.start} onChange={set('start')} /></label>
        <label className="text-xs flex items-center gap-2">{t('إلى', 'To')}
          <input type="date" className="input-field text-sm" value={d.end} onChange={set('end')} /></label>
        <label className="text-xs flex items-center gap-2">{t('مكافأة لكل عضو', 'Bonus per member')}
          <input type="number" className="input-field text-sm w-24" value={d.bonus_per_member} onChange={set('bonus_per_member')} /></label>
        <label className="text-xs flex items-center gap-2">{t('أقل عدد أعضاء للفرع', 'Minimum branch members')}
          <input type="number" className="input-field text-sm w-20" value={d.min_members} onChange={set('min_members')} /></label>
      </div>
      <div>
        <div className="text-xs text-gray-500 mb-1">
          {t('الفروع (بدون اختيار = كل الفروع)', 'Branches (none chosen = all branches)')}
        </div>
        <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
          {branches.map(b => (
            <button key={b.id} type="button" onClick={() => toggleBranch(b.id)}
                    className={`text-xs rounded-full px-2 py-0.5 border ${d.branch_ids.includes(b.id) ? 'bg-brand-500 text-white border-brand-500' : 'bg-white text-gray-600 border-gray-200'}`}>
              {lang === 'en' ? (b.name_en || b.name) : (b.name_ar || b.name)}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <button className="btn-primary text-xs" disabled={busy || !d.name_ar || !d.name_en || d.target === '' || !d.start || !d.end}
                onClick={() => onSave({ ...d, target: Number(d.target), bonus_per_member: Number(d.bonus_per_member),
                                        min_members: Number(d.min_members) })}>
          {t('حفظ التحدي', 'Save challenge')}
        </button>
        <button className="btn-secondary text-xs" onClick={onCancel}>{t('تراجع', 'Back')}</button>
      </div>
    </div>
  )
}

export default function ChallengesTab({ t, lang }) {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [msg, setMsg] = useState(null)
  const flash = (text, ok = true) => { setMsg({ text, ok }); setTimeout(() => setMsg(null), 5000) }
  const errText = (e) => e?.response?.data?.detail || Object.values(e?.response?.data || {}).join(' · ') || t('حدث خطأ', 'Error')
  const { data, isLoading } = useQuery({
    queryKey: ['gamificationChallenges'], queryFn: () => gamificationApi.challenges().then(r => r.data),
  })
  const refresh = () => ['gamificationChallenges', 'gamificationMe'].forEach(k => qc.invalidateQueries({ queryKey: [k] }))
  const create = useMutation({
    mutationFn: (p) => gamificationApi.createChallenge(p),
    onSuccess: () => { setAdding(false); refresh(); flash(t('تم إنشاء التحدي', 'Challenge created')) },
    onError: (e) => flash(errText(e), false),
  })
  const toggle = useMutation({
    mutationFn: (c) => gamificationApi.updateChallenge(c.id, { is_active: !c.is_active }),
    onSuccess: refresh, onError: (e) => flash(errText(e), false),
  })
  const evaluate = useMutation({
    mutationFn: (c) => gamificationApi.evaluateChallenge(c.id),
    onSuccess: () => { refresh(); flash(t('تم التقييم ومنح المكافآت', 'Judged — bonuses awarded')) },
    onError: (e) => flash(errText(e), false),
  })
  if (isLoading || !data) return <div className="h-60 animate-pulse bg-gray-50 rounded-lg" />
  const list = data.challenges || []
  return (
    <div className="space-y-4">
      {msg && <div className={`rounded-lg text-sm px-3 py-2 ${msg.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>{msg.text}</div>}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-gray-500">
          {t('هدف مشترك لكل الفرع: لو حققه الفرع بنهاية الفترة يحصل كل أعضائه على المكافأة. المكافأة تزيد الخبرة والرصيد ولا تدخل في الترتيب.',
             'A shared goal for the whole branch: if the branch meets it by the end of the period, every member gets the bonus. Bonuses raise XP and balance but never count in rankings.')}
        </p>
        {data.can_edit && !adding && (
          <button className="btn-secondary text-xs" onClick={() => setAdding(true)}>➕ {t('تحدٍ جديد', 'New challenge')}</button>
        )}
      </div>
      {adding && <NewChallengeForm t={t} lang={lang} busy={create.isPending}
                                   onSave={(p) => create.mutate(p)} onCancel={() => setAdding(false)} />}
      {list.length === 0
        ? <div className="card text-sm text-gray-400">{t('لا توجد تحديات حالياً.', 'No challenges right now.')}</div>
        : list.map(c => (
          <ChallengeCard key={c.id} c={c} t={t} lang={lang} canEdit={data.can_edit} myBranchId={data.my_branch_id}
                         busy={toggle.isPending || evaluate.isPending}
                         onToggle={(x) => toggle.mutate(x)} onEvaluate={(x) => evaluate.mutate(x)} />
        ))}
    </div>
  )
}
