/**
 * Reward catalog tabs for /gamification.
 *   RewardsTab          🎁 المكافآت — balance, catalog, request inline, my requests (everyone)
 *   RedemptionsTab      📦 طلبات المكافآت — every request; deliver / cancel (managers)
 *   RewardCatalogEditor catalog editor shown inside ⚙️ الإعدادات (editors)
 *
 * The server decides eligibility, balance, stock and permissions; this only displays.
 * Approvals happen in the existing /approvals inbox (branch manager → management).
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { gamificationApi } from '../../api/client'

const fmt = (n) => (n ?? 0).toLocaleString('en-US')

export const REWARD_CATEGORIES = [
  ['time_off', 'وقت راحة', 'Time off'], ['voucher', 'قسائم وهدايا', 'Vouchers & gifts'],
  ['recognition', 'تقدير معنوي', 'Recognition'], ['development', 'تطوير وتدريب', 'Development'],
  ['perk', 'مزايا', 'Perks'],
]

const STATUS = {
  pending:   ['بانتظار الموافقة', 'Waiting for approval', 'bg-amber-50 text-amber-800'],
  approved:  ['معتمد — بانتظار التسليم', 'Approved — to be delivered', 'bg-sky-50 text-sky-800'],
  fulfilled: ['تم التسليم', 'Delivered', 'bg-emerald-50 text-emerald-700'],
  rejected:  ['مرفوض — أعيدت النقاط', 'Rejected — points returned', 'bg-red-50 text-red-700'],
  cancelled: ['ملغي — أعيدت النقاط', 'Cancelled — points returned', 'bg-gray-100 text-gray-600'],
}

export function StatusChip({ status, t }) {
  const [ar, en, cls] = STATUS[status] || [status, status, 'bg-gray-100']
  return <span className={`text-[11px] font-bold rounded-full px-2 py-0.5 whitespace-nowrap ${cls}`}>{t(ar, en)}</span>
}

const errText = (e, t) => e?.response?.data?.detail
  || Object.values(e?.response?.data || {}).join(' · ') || t('حدث خطأ', 'Something went wrong')

function Flash({ msg }) {
  if (!msg) return null
  return <div className={`rounded-lg text-sm px-3 py-2 ${msg.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>{msg.text}</div>
}

function useFlash() {
  const [msg, setMsg] = useState(null)
  return [msg, (text, ok = true) => { setMsg({ text, ok }); setTimeout(() => setMsg(null), 5000) }]
}

function invalidateAll(qc) {
  ['gamificationRewards', 'gamificationWallet', 'gamificationMe', 'gamificationRedemptions']
    .forEach(k => qc.invalidateQueries({ queryKey: [k] }))
}

// ── 🎁 everyone ───────────────────────────────────────────────────────────────

function RewardCard({ r, t, lang, onRedeem, busy }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  return (
    <div className={`card flex flex-col ${r.can_request ? '' : 'opacity-75'}`}>
      <div className="flex items-start gap-3">
        <span className="text-3xl">{r.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="font-black text-gray-900">{lang === 'en' ? r.name_en : r.name_ar}</div>
          <div className="text-xs text-gray-500">{lang === 'en' ? r.desc_en : r.desc_ar}</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px] text-gray-500">
        {r.min_level > 1 && <span className="rounded bg-gray-100 px-1.5 py-0.5">{t(`مستوى ${r.min_level}+`, `Level ${r.min_level}+`)}</span>}
        {r.limit_per_month && <span className="rounded bg-gray-100 px-1.5 py-0.5">{t(`${r.limit_per_month} شهرياً`, `${r.limit_per_month}/month`)}</span>}
        {r.stock != null && <span className="rounded bg-gray-100 px-1.5 py-0.5">{t(`المتاح ${r.stock}`, `${r.stock} left`)}</span>}
        {!r.requires_approval && <span className="rounded bg-emerald-50 text-emerald-700 px-1.5 py-0.5">{t('بدون موافقة', 'No approval')}</span>}
      </div>
      <div className="mt-auto pt-3 flex items-center justify-between gap-2">
        <span className="font-black text-brand-700">{fmt(r.cost)} {t('نقطة', 'pts')}</span>
        {r.can_request
          ? !open && <button className="btn-primary text-xs" onClick={() => setOpen(true)}>{t('استبدال', 'Redeem')}</button>
          : <span className="text-[11px] text-gray-400 text-end">{lang === 'en' ? r.blocked_en : r.blocked_ar}</span>}
      </div>
      {open && (
        <div className="mt-3 space-y-2 border-t border-gray-100 pt-3">
          <input className="input-field text-sm" placeholder={t('ملاحظة (اختياري) — مثلاً اليوم المفضل', 'Note (optional) — e.g. preferred date')}
                 value={note} onChange={e => setNote(e.target.value)} maxLength={300} />
          <div className="flex gap-2">
            <button className="btn-primary text-xs flex-1" disabled={busy}
                    onClick={() => onRedeem(r, note, () => { setOpen(false); setNote('') })}>
              {t(`تأكيد — خصم ${fmt(r.cost)} نقطة`, `Confirm — spend ${fmt(r.cost)} pts`)}
            </button>
            <button className="btn-secondary text-xs" onClick={() => setOpen(false)}>{t('تراجع', 'Back')}</button>
          </div>
          {r.requires_approval && (
            <p className="text-[11px] text-gray-400">
              {t('تُحجز النقاط حتى يوافق مدير الفرع ثم الإدارة، وتعود لرصيدك عند الرفض.',
                 'Points are held until the branch manager and management approve; they come back if rejected.')}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function RewardsTab({ t, lang }) {
  const qc = useQueryClient()
  const [msg, flash] = useFlash()
  const [cat, setCat] = useState('')
  const { data } = useQuery({
    queryKey: ['gamificationRewards'], queryFn: () => gamificationApi.rewards().then(r => r.data),
  })
  const { data: mine } = useQuery({
    queryKey: ['gamificationWallet'], queryFn: () => gamificationApi.wallet().then(r => r.data),
  })
  const redeem = useMutation({
    mutationFn: ({ r, note }) => gamificationApi.redeem({ reward_id: r.id, note }),
    onSuccess: (res, { done }) => {
      done(); invalidateAll(qc)
      flash(res.data.status === 'approved'
        ? t('تم — المكافأة معتمدة وبانتظار التسليم', 'Done — approved, waiting for delivery')
        : t('تم إرسال الطلب للموافقة', 'Request sent for approval'))
    },
    onError: (e) => flash(errText(e, t), false),
  })
  const cancel = useMutation({
    mutationFn: (id) => gamificationApi.cancelRedemption(id),
    onSuccess: () => { invalidateAll(qc); flash(t('أُلغي الطلب وعادت النقاط', 'Cancelled — points returned')) },
    onError: (e) => flash(errText(e, t), false),
  })
  const w = data?.wallet || mine?.wallet
  const list = (data?.rewards || []).filter(r => !cat || r.category === cat)
  const cats = REWARD_CATEGORIES.filter(([k]) => (data?.rewards || []).some(r => r.category === k))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="card text-center py-3 col-span-2 sm:col-span-1">
          <div className="text-2xl font-black text-brand-700">🎁 {fmt(w?.balance)}</div>
          <div className="text-xs text-gray-500">{t('رصيدك المتاح', 'Available balance')}</div>
        </div>
        <div className="card text-center py-3"><div className="text-lg font-black">{fmt(w?.earned_net)}</div>
          <div className="text-xs text-gray-500">{t('صافي ما كسبته', 'Net earned')}</div></div>
        <div className="card text-center py-3"><div className="text-lg font-black text-amber-700">{fmt(w?.held)}</div>
          <div className="text-xs text-gray-500">{t('محجوز لطلبات معلقة', 'Held by pending requests')}</div></div>
        <div className="card text-center py-3"><div className="text-lg font-black text-gray-600">{fmt(w?.spent)}</div>
          <div className="text-xs text-gray-500">{t('تم استبداله', 'Redeemed')}</div></div>
      </div>
      <p className="text-xs text-gray-500">
        {t('الاستبدال لا يخفض مستواك ولا ترتيبك — ينقص الرصيد فقط.',
           'Redeeming never lowers your level or rank — only your balance.')}
      </p>
      <Flash msg={msg} />
      {cats.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {[['', 'الكل', 'All'], ...cats].map(([k, ar, en]) => (
            <button key={k} onClick={() => setCat(k)}
                    className={`text-xs font-bold rounded-full px-3 py-1 border ${cat === k ? 'bg-brand-500 text-white border-brand-500' : 'bg-white text-gray-600 border-gray-200'}`}>
              {t(ar, en)}
            </button>
          ))}
        </div>
      )}
      {list.length === 0
        ? <div className="card text-sm text-gray-400">{t('لا توجد مكافآت متاحة حالياً.', 'No rewards available right now.')}</div>
        : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {list.map(r => <RewardCard key={r.id} r={r} t={t} lang={lang} busy={redeem.isPending}
                                       onRedeem={(rw, note, done) => redeem.mutate({ r: rw, note, done })} />)}
          </div>
        )}
      <div className="card">
        <div className="font-black text-gray-900 mb-2">{t('🧾 طلباتي', '🧾 My requests')}</div>
        {(mine?.redemptions || []).length === 0
          ? <p className="text-sm text-gray-400">{t('لم تطلب مكافآت بعد.', 'No requests yet.')}</p>
          : (
            <ul className="divide-y divide-gray-100">
              {mine.redemptions.map(x => (
                <li key={x.id} className="py-2 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="min-w-0">
                    {x.reward.icon} {lang === 'en' ? x.reward.name_en : x.reward.name_ar}
                    <span className="text-xs text-gray-400 mx-1">{String(x.created_at).slice(0, 10)} · {fmt(x.cost)} {t('نقطة', 'pts')}</span>
                    {(x.fulfillment_note || x.decision_note) && (
                      <div className="text-xs text-gray-500">{x.fulfillment_note || x.decision_note}</div>
                    )}
                  </span>
                  <span className="flex items-center gap-2">
                    <StatusChip status={x.status} t={t} />
                    {x.status === 'pending' && (
                      <button className="text-xs text-red-600 underline" disabled={cancel.isPending}
                              onClick={() => cancel.mutate(x.id)}>{t('إلغاء', 'Cancel')}</button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
      </div>
    </div>
  )
}

// ── 📦 managers ───────────────────────────────────────────────────────────────

function RedemptionRow({ x, t, lang, canEdit, onFulfil, onCancel, busy }) {
  const [mode, setMode] = useState(null)        // 'fulfil' | 'cancel'
  const [text, setText] = useState('')
  return (
    <li className="py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0">
          <b>{x.staff_name}</b> <span className="text-xs text-gray-400">{x.branch}</span>
          <div>{x.reward.icon} {lang === 'en' ? x.reward.name_en : x.reward.name_ar}
            <span className="text-xs text-gray-400 mx-1">{fmt(x.cost)} {t('نقطة', 'pts')} · {String(x.created_at).slice(0, 10)}</span></div>
          {x.note && <div className="text-xs text-gray-500">📝 {x.note}</div>}
          {(x.fulfillment_note || x.decision_note) && <div className="text-xs text-gray-500">{x.fulfillment_note || x.decision_note}</div>}
        </span>
        <span className="flex items-center gap-2">
          <StatusChip status={x.status} t={t} />
          {x.status === 'pending' && x.approval_request_id && (
            <Link to="/approvals" className="text-xs text-brand-700 underline">{t('صندوق الموافقات', 'Approvals inbox')}</Link>
          )}
          {canEdit && x.status === 'approved' && !mode && (
            <>
              <button className="btn-primary text-xs" onClick={() => setMode('fulfil')}>{t('تم التسليم', 'Mark delivered')}</button>
              <button className="btn-secondary text-xs" onClick={() => setMode('cancel')}>{t('إلغاء', 'Cancel')}</button>
            </>
          )}
        </span>
      </div>
      {mode && (
        <div className="mt-2 flex flex-wrap gap-2">
          <input className="input-field text-sm flex-1 min-w-[200px]" value={text} onChange={e => setText(e.target.value)}
                 placeholder={mode === 'fulfil'
                   ? t('تفاصيل التسليم (التاريخ، كود القسيمة…)', 'Delivery details (date, voucher code…)')
                   : t('سبب الإلغاء (إلزامي) — ستعود النقاط', 'Reason (required) — points are returned')} />
          <button className="btn-primary text-xs" disabled={busy || (mode === 'cancel' && text.trim().length < 5)}
                  onClick={() => (mode === 'fulfil' ? onFulfil : onCancel)(x.id, text, () => { setMode(null); setText('') })}>
            {t('تأكيد', 'Confirm')}
          </button>
          <button className="btn-secondary text-xs" onClick={() => setMode(null)}>{t('تراجع', 'Back')}</button>
        </div>
      )}
    </li>
  )
}

export function RedemptionsTab({ t, lang, canEdit }) {
  const qc = useQueryClient()
  const [msg, flash] = useFlash()
  const [status, setStatus] = useState('approved')
  const { data = [], isLoading } = useQuery({
    queryKey: ['gamificationRedemptions', status],
    queryFn: () => gamificationApi.redemptions({ status: status || undefined }).then(r => r.data),
  })
  const fulfil = useMutation({
    mutationFn: ({ id, text }) => gamificationApi.fulfilRedemption(id, { note: text }),
    onSuccess: (_, { done }) => { done(); invalidateAll(qc); flash(t('سُجّل التسليم وأُبلغ الموظف', 'Delivered — the employee was notified')) },
    onError: (e) => flash(errText(e, t), false),
  })
  const cancel = useMutation({
    mutationFn: ({ id, text }) => gamificationApi.cancelRedemption(id, { reason: text }),
    onSuccess: (_, { done }) => { done(); invalidateAll(qc); flash(t('أُلغي الطلب وعادت النقاط للموظف', 'Cancelled — points returned')) },
    onError: (e) => flash(errText(e, t), false),
  })
  const tabs = [['approved', 'بانتظار التسليم', 'To deliver'], ['pending', 'بانتظار الموافقة', 'Waiting approval'],
                ['fulfilled', 'تم التسليم', 'Delivered'], ['rejected,cancelled', 'مرفوض / ملغي', 'Rejected / cancelled'],
                ['', 'الكل', 'All']]
  return (
    <div className="card space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {tabs.map(([k, ar, en]) => (
          <button key={k} onClick={() => setStatus(k)}
                  className={`text-xs font-bold rounded-full px-3 py-1 border ${status === k ? 'bg-brand-500 text-white border-brand-500' : 'bg-white text-gray-600 border-gray-200'}`}>
            {t(ar, en)}
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-500">
        {t('الموافقة على الطلبات تتم من صندوق الموافقات (مدير الفرع ثم الإدارة). هنا تُسجّل التسليم بعد الاعتماد.',
           'Requests are approved in the approvals inbox (branch manager, then management). Record delivery here once approved.')}
      </p>
      <Flash msg={msg} />
      {isLoading ? <div className="h-32 animate-pulse bg-gray-50 rounded-lg" />
        : data.length === 0 ? <p className="text-sm text-gray-400">{t('لا توجد طلبات.', 'No requests.')}</p>
        : (
          <ul className="divide-y divide-gray-100">
            {data.map(x => (
              <RedemptionRow key={x.id} x={x} t={t} lang={lang} canEdit={canEdit}
                             busy={fulfil.isPending || cancel.isPending}
                             onFulfil={(id, text, done) => fulfil.mutate({ id, text, done })}
                             onCancel={(id, text, done) => cancel.mutate({ id, text, done })} />
            ))}
          </ul>
        )}
    </div>
  )
}

// ── ⚙️ editors ────────────────────────────────────────────────────────────────

const EMPTY = { name_ar: '', name_en: '', desc_ar: '', desc_en: '', icon: '🎁', category: 'perk',
                cost: '', stock: '', limit_per_month: '', min_level: 1, requires_approval: true, is_active: true }

function RewardForm({ initial, t, onSave, onCancel, busy }) {
  const [d, setD] = useState({ ...EMPTY, ...initial,
    stock: initial?.stock ?? '', limit_per_month: initial?.limit_per_month ?? '' })
  const set = (k) => (e) => setD({ ...d, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const payload = () => ({ ...d, cost: Number(d.cost), min_level: Number(d.min_level) || 1,
    stock: d.stock === '' ? null : Number(d.stock),
    limit_per_month: d.limit_per_month === '' ? null : Number(d.limit_per_month) })
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 bg-gray-50 rounded-lg p-3">
      <input className="input-field text-xs" placeholder={t('الاسم بالعربي', 'Arabic name')} value={d.name_ar} onChange={set('name_ar')} />
      <input className="input-field text-xs" dir="ltr" placeholder="English name" value={d.name_en} onChange={set('name_en')} />
      <input className="input-field text-xs" placeholder={t('الشرح بالعربي', 'Arabic description')} value={d.desc_ar} onChange={set('desc_ar')} />
      <input className="input-field text-xs" dir="ltr" placeholder="English description" value={d.desc_en} onChange={set('desc_en')} />
      <input className="input-field text-xs" placeholder={t('أيقونة', 'Icon')} value={d.icon} onChange={set('icon')} maxLength={8} />
      <select className="input-field text-xs" value={d.category} onChange={set('category')}>
        {REWARD_CATEGORIES.map(([k, ar, en]) => <option key={k} value={k}>{t(ar, en)}</option>)}
      </select>
      <input type="number" className="input-field text-xs" placeholder={t('التكلفة (نقاط)', 'Cost (points)')} value={d.cost} onChange={set('cost')} />
      <input type="number" className="input-field text-xs" placeholder={t('أقل مستوى', 'Min level')} value={d.min_level} onChange={set('min_level')} />
      <input type="number" className="input-field text-xs" placeholder={t('المتاح (فارغ = بلا حد)', 'Stock (empty = unlimited)')} value={d.stock} onChange={set('stock')} />
      <input type="number" className="input-field text-xs" placeholder={t('حد شهري للموظف', 'Monthly limit per person')} value={d.limit_per_month} onChange={set('limit_per_month')} />
      <label className="text-xs flex items-center gap-1.5"><input type="checkbox" checked={d.requires_approval} onChange={set('requires_approval')} />{t('يحتاج موافقة', 'Needs approval')}</label>
      <label className="text-xs flex items-center gap-1.5"><input type="checkbox" checked={d.is_active} onChange={set('is_active')} />{t('متاحة للموظفين', 'Visible to staff')}</label>
      <div className="col-span-2 sm:col-span-4 flex gap-2">
        <button className="btn-primary text-xs" disabled={busy || !d.name_ar || !d.name_en || !d.cost} onClick={() => onSave(payload())}>{t('حفظ', 'Save')}</button>
        <button className="btn-secondary text-xs" onClick={onCancel}>{t('تراجع', 'Back')}</button>
      </div>
    </div>
  )
}

export function RewardCatalogEditor({ t, lang }) {
  const qc = useQueryClient()
  const [msg, flash] = useFlash()
  const [editing, setEditing] = useState(null)    // reward id | 'new' | null
  const { data } = useQuery({
    queryKey: ['gamificationRewards', 'all'], queryFn: () => gamificationApi.rewards({ all: 1 }).then(r => r.data),
  })
  const save = useMutation({
    mutationFn: (p) => (editing === 'new' ? gamificationApi.createReward(p) : gamificationApi.updateReward(editing, p)),
    onSuccess: () => { setEditing(null); invalidateAll(qc); flash(t('تم الحفظ', 'Saved')) },
    onError: (e) => flash(errText(e, t), false),
  })
  const toggle = useMutation({
    mutationFn: (r) => gamificationApi.updateReward(r.id, { is_active: !r.is_active }),
    onSuccess: () => invalidateAll(qc),
    onError: (e) => flash(errText(e, t), false),
  })
  return (
    <div className="card space-y-2">
      <div className="flex items-center justify-between">
        <div className="font-black">{t('🎁 كتالوج المكافآت', '🎁 Reward catalog')}</div>
        {editing !== 'new' && <button className="btn-secondary text-xs" onClick={() => setEditing('new')}>➕ {t('مكافأة جديدة', 'New reward')}</button>}
      </div>
      <p className="text-[11px] text-gray-400">
        {t('المكافآت التي تكلف الشركة مالاً أو وقت عمل تبدأ موقوفة — حدّد تكلفتها بالنقاط ثم فعّلها.',
           'Rewards that cost the company money or working time start switched off — set their point cost, then switch them on.')}
      </p>
      <Flash msg={msg} />
      {editing === 'new' && <RewardForm t={t} busy={save.isPending} onSave={(p) => save.mutate(p)} onCancel={() => setEditing(null)} />}
      <ul className="divide-y divide-gray-100">
        {(data?.rewards || []).map(r => (
          <li key={r.id} className="py-2 text-sm">
            {editing === r.id
              ? <RewardForm initial={r} t={t} busy={save.isPending} onSave={(p) => save.mutate(p)} onCancel={() => setEditing(null)} />
              : (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className={r.is_active ? '' : 'text-gray-400'}>
                    {r.icon} {lang === 'en' ? r.name_en : r.name_ar}
                    <span className="text-xs text-gray-400 mx-1">
                      {fmt(r.cost)} {t('نقطة', 'pts')}{r.stock != null ? ` · ${t('المتاح', 'stock')} ${r.stock}` : ''}
                      {r.min_level > 1 ? ` · ${t('مستوى', 'level')} ${r.min_level}+` : ''}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <label className="text-xs flex items-center gap-1">
                      <input type="checkbox" checked={r.is_active} disabled={toggle.isPending} onChange={() => toggle.mutate(r)} />
                      {t('متاحة', 'On')}
                    </label>
                    <button className="btn-secondary text-xs" onClick={() => setEditing(r.id)}>{t('تعديل', 'Edit')}</button>
                  </span>
                </div>
              )}
          </li>
        ))}
      </ul>
    </div>
  )
}
