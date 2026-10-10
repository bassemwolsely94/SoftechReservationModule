/**
 * ChampionsTab — /gamification?tab=champions (👑 أبطال الشهر).
 *   • The race this month (live): leaders per role in my branch and on the network.
 *   • Hall of fame: a crowned month's network podium per role, branch champions,
 *     and the branch of the month. Month picker for past months.
 *   • Editors: crown last month now (normally automatic on the 1st) and revoke a title
 *     with a written reason (the server reverses its bonus).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { gamificationApi } from '../../api/client'
import { roleLabel } from './labels'

const fmt = (n) => (n ?? 0).toLocaleString('en-US')
const MEDAL = { 1: '🥇', 2: '🥈', 3: '🥉' }
const ym = (d) => String(d || '').slice(0, 7)

function Leaders({ title, groups, t, showBranch }) {
  const roles = Object.keys(groups || {})
  return (
    <div className="card">
      <div className="font-black text-gray-900 mb-2">{title}</div>
      {roles.length === 0
        ? <p className="text-sm text-gray-400">{t('لا نقاط بعد هذا الشهر.', 'No points yet this month.')}</p>
        : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {roles.map(role => (
              <div key={role} className="rounded-lg bg-gray-50 p-3">
                <div className="text-xs font-bold text-gray-500 mb-1">{roleLabel(role, t)}</div>
                <ol className="space-y-1">
                  {groups[role].map(r => (
                    <li key={r.staff_id} className="flex justify-between text-sm">
                      <span>{MEDAL[r.rank]} {r.name}{showBranch && r.branch ? <span className="text-xs text-gray-400"> · {r.branch}</span> : null}</span>
                      <b>{fmt(r.net)}</b>
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        )}
    </div>
  )
}

function RevokeButton({ c, t, onRevoke, busy }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  if (c.revoked) return <span className="text-[11px] text-red-600">{t('لقب مسحوب', 'Revoked')}</span>
  if (!open) return <button className="text-[11px] text-gray-400 underline" onClick={() => setOpen(true)}>{t('سحب اللقب', 'Revoke')}</button>
  return (
    <span className="flex gap-1">
      <input className="input-field text-xs w-44" value={reason} onChange={e => setReason(e.target.value)}
             placeholder={t('السبب (إلزامي)', 'Reason (required)')} />
      <button className="btn-primary text-xs" disabled={busy || reason.trim().length < 5}
              onClick={() => onRevoke(c.id, reason, () => setOpen(false))}>{t('تأكيد', 'Confirm')}</button>
      <button className="btn-secondary text-xs" onClick={() => setOpen(false)}>{t('تراجع', 'Back')}</button>
    </span>
  )
}

export default function ChampionsTab({ t, lang }) {
  const qc = useQueryClient()
  const [month, setMonth] = useState('')
  const [msg, setMsg] = useState(null)
  const flash = (text, ok = true) => { setMsg({ text, ok }); setTimeout(() => setMsg(null), 5000) }
  const errText = (e) => e?.response?.data?.detail || Object.values(e?.response?.data || {}).join(' · ') || t('حدث خطأ', 'Error')
  const { data, isLoading } = useQuery({
    queryKey: ['gamificationChampions', month],
    queryFn: () => gamificationApi.champions(month ? { month } : {}).then(r => r.data),
  })
  const refresh = () => ['gamificationChampions', 'gamificationMe'].forEach(k => qc.invalidateQueries({ queryKey: [k] }))
  const crown = useMutation({
    mutationFn: () => gamificationApi.crownChampions({}),
    onSuccess: (r) => { refresh(); flash(r.data.created ? t('تم تتويج أبطال الشهر الماضي', 'Last month crowned') : t('الشهر متوَّج بالفعل', 'Already crowned')) },
    onError: (e) => flash(errText(e), false),
  })
  const revoke = useMutation({
    mutationFn: ({ id, reason }) => gamificationApi.revokeChampion(id, { reason }),
    onSuccess: (_, { done }) => { done(); refresh(); flash(t('سُحب اللقب وخُصمت مكافأته', 'Title revoked, bonus reversed')) },
    onError: (e) => flash(errText(e), false),
  })
  if (isLoading || !data) return <div className="h-60 animate-pulse bg-gray-50 rounded-lg" />
  const race = data.race || {}
  const champs = data.champions || []
  const network = champs.filter(c => c.kind === 'network')
  const byRole = network.reduce((g, c) => { (g[c.role] ||= []).push(c); return g }, {})
  const branchChamps = champs.filter(c => c.kind === 'branch')
  const bom = champs.find(c => c.kind === 'branch_of_month')
  const label = lang === 'en' ? data.label_en : data.label_ar
  return (
    <div className="space-y-4">
      {msg && <div className={`rounded-lg text-sm px-3 py-2 ${msg.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>{msg.text}</div>}

      <div className="card bg-gradient-to-l from-amber-50 to-white">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-black text-gray-900">{t('🏁 سباق هذا الشهر', '🏁 This month\'s race')}</div>
            <div className="text-xs text-gray-500">
              {t(`باقي ${race.days_left} يوم — يُتوَّج الأبطال تلقائياً أول الشهر القادم`,
                 `${race.days_left} days left — champions are crowned automatically on the 1st`)}
            </div>
          </div>
          <div className="text-xs text-gray-500">
            {t('بطل الفرع +200 · بطل الشبكة +500 · الثاني والثالث +200 — المكافأة لا تدخل في الترتيب',
               'Branch champion +200 · Network champion +500 · 2nd/3rd +200 — bonuses never count in the ranking')}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Leaders title={t('🏠 المتصدرون في فرعي', '🏠 Leading in my branch')} groups={race.my_branch} t={t} />
        <Leaders title={t('🌍 المتصدرون على الشبكة', '🌍 Leading on the network')} groups={race.network} t={t} showBranch />
      </div>

      <div className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="font-black text-gray-900">
            {t('👑 لوحة الأبطال', '👑 Hall of fame')}{label ? ` — ${label}` : ''}
          </div>
          <div className="flex items-center gap-2">
            {data.months?.length > 0 && (
              <select className="input-field text-xs w-auto" value={month || ym(data.month)}
                      onChange={e => setMonth(e.target.value)}>
                {data.months.map(m => <option key={m} value={ym(m)}>{ym(m)}</option>)}
              </select>
            )}
            {data.can_edit && (
              <button className="btn-secondary text-xs" disabled={crown.isPending} onClick={() => crown.mutate()}>
                👑 {t('تتويج الشهر الماضي الآن', 'Crown last month now')}
              </button>
            )}
          </div>
        </div>
        {!data.month ? (
          <p className="text-sm text-gray-400">{t('لم يُتوَّج أي شهر بعد — أول تتويج في بداية الشهر القادم.',
                                                  'No month crowned yet — the first crowning is at the start of next month.')}</p>
        ) : (
          <>
            {bom && (
              <div className="rounded-lg bg-brand-50 p-3 text-sm">
                🏢 {t('فرع الشهر', 'Branch of the month')}: <b>{bom.branch}</b>
                <span className="text-xs text-gray-500"> · {fmt(bom.players)} {t('لاعب', 'players')}</span>
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {Object.entries(byRole).map(([role, list]) => (
                <div key={role} className="rounded-lg border border-amber-200 bg-amber-50/40 p-3">
                  <div className="text-xs font-bold text-amber-800 mb-1">{t('منصة الشبكة', 'Network podium')} — {roleLabel(role, t)}</div>
                  {list.sort((a, b) => a.rank - b.rank).map(c => (
                    <div key={c.id} className={`flex items-center justify-between gap-2 text-sm py-0.5 ${c.revoked ? 'line-through text-gray-400' : ''}`}>
                      <span>{MEDAL[c.rank]} {c.name} <span className="text-xs text-gray-400">{c.branch}</span></span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">{fmt(c.net)}</span>
                        {data.can_edit && <RevokeButton c={c} t={t} busy={revoke.isPending}
                                                        onRevoke={(id, reason, done) => revoke.mutate({ id, reason, done })} />}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            {branchChamps.length > 0 && (
              <div>
                <div className="text-sm font-black mb-1">{t('👑 أبطال الفروع', '👑 Branch champions')}</div>
                <ul className="divide-y divide-gray-100">
                  {branchChamps.map(c => (
                    <li key={c.id} className={`py-1.5 flex flex-wrap items-center justify-between gap-2 text-sm ${c.revoked ? 'line-through text-gray-400' : ''}`}>
                      <span>{c.branch} · <span className="text-gray-500">{roleLabel(c.role, t)}</span>: <b>{c.name}</b></span>
                      <span className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">{fmt(c.net)} · {t(`من ${c.players}`, `of ${c.players}`)}</span>
                        {data.can_edit && <RevokeButton c={c} t={t} busy={revoke.isPending}
                                                        onRevoke={(id, reason, done) => revoke.mutate({ id, reason, done })} />}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
