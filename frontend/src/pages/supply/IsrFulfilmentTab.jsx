/**
 * IsrFulfilmentTab.jsx — /supply «تلبية طلبات الفروع»: one or more SOFTECH ISRs raised by
 * branches → per item: requesting branch, every other branch, HQ (stock / rate / need /
 * max / excess) and the plan (other branches' excess → HQ → shortage to buy).
 *
 * READ-ONLY. The backend (apps/purchasing/isr_fulfillment.py) owns every number; this
 * screen only shows them. Changing the coverage re-plans on the same SOFTECH snapshot
 * (token) — «تحديث من SOFTECH» re-reads live stock. Excel export = the same snapshot as a
 * formula-driven workbook (edit its yellow coverage cell and it re-plans itself).
 */
import { Fragment, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import { Chip, q, money, downloadBlob, inputCls, btnPrimary, btnGhost } from './supplyUi'
import useBranchLabels from '../../hooks/useBranchLabels'
import ProgressBar from '../../components/ProgressBar'

const RETURN_TONE = { proposed: 'amber', approved: 'blue', pushed: 'emerald', failed: 'rose', cancelled: 'gray' }

// SOFTECH user code + its userid, e.g. '1776 · Carol adel' (name only when known)
const userLabel = (code, name) => (name ? `${code} · ${name}` : (code || '—'))

// '261609, 2615043' → ['261609', '2615043'] (display-side only; the backend validates)
const splitIsrs = (text) => text.split(/[\s,،;]+/).map(s => s.trim()).filter(Boolean)

const FILTERS = [
  ['all', 'الكل'], ['short', 'به نقص'], ['by_branches', 'مغطى من الفروع'],
  ['full', 'مغطى بالكامل'], ['over', 'يتجاوز الحد الأقصى'],
]

async function blobErr(err) {
  const d = err?.response?.data
  if (d instanceof Blob) {
    try { return JSON.parse(await d.text()).detail } catch { /* not JSON */ }
  }
  return d?.detail || 'تعذّر تنفيذ العملية'
}

// The three deterministic plan factors (apps/purchasing/isr_fulfillment.plan_settings):
//   coverage — months each DONOR keeps (its ceiling); fill — months the REQUESTING branch is
//   filled up to (the recommended qty); basis — which quantity the plan ships.
export const BASIS_OPTIONS = [
  ['min', 'الأقل من الاثنين'], ['recommended', 'الموصى بها'], ['requested', 'المطلوبة'],
]
export const DEFAULT_SETTINGS = { coverage: 1, fill: 1.5, basis: 'min' }   // donors keep 1 month
export const settingsBody = (st) => ({
  coverage: Number(st.coverage) || 1, fill_coverage: Number(st.fill) || 1.5, basis: st.basis || 'min',
})
// the settings an analysed plan was computed with — proposals / transfers reuse exactly these
export const planBody = (plan) => ({ coverage: plan.coverage, fill_coverage: plan.fill_coverage, basis: plan.basis })
export const settingsChanged = (st, plan) => !!plan && (Number(st.coverage) !== plan.coverage
  || Number(st.fill) !== plan.fill_coverage || st.basis !== plan.basis)

export function PlanSettings({ value, onChange }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value })
  return (
    <>
      <label className="flex flex-col gap-1 text-xs text-content/70"
        title="الاحتياج = هذه الشهور × معدل بيع الفرع الطالب − رصيده − الرصيد بالطريق؛ إذا كان موجباً يُقرَّب لأعلى (عبوة على الأقل) وإلا صفر. الكمية الموصى بها = الاحتياج (صنف لا يبيعه الفرع = الكمية المطلوبة).">
        تغطية الفرع الطالب (شهور)
        <input type="number" step="0.25" min="0.25" max="12" value={value.fill}
          onChange={set('fill')} className={`${inputCls} w-24`} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-content/70" title="أي كمية تُوزَّع على الفروع/الرئيسي/النقص">
        الكمية التي تُوزَّع
        <select value={value.basis} onChange={set('basis')} className={`${inputCls} w-36`}>
          {BASIS_OPTIONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-content/70"
        title="ما يحتفظ به كل فرع مانح: معدل بيعه × هذه الشهور (لا يقل عن عبوة)؛ ما فوقه فائض قابل للنقل">
        تغطية الفروع المانحة (شهور)
        <input type="number" step="0.25" min="0.25" max="12" value={value.coverage}
          onChange={set('coverage')} className={`${inputCls} w-24`} />
      </label>
    </>
  )
}

export default function IsrFulfilmentTab() {
  const [isrText, setIsrText] = useState('')
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [plan, setPlan] = useState(null)
  const [error, setError] = useState('')
  const [exportErr, setExportErr] = useState('')

  const body = (extra = {}) => ({
    isrs: isrText, ...settingsBody(settings),
    token: plan?.token, ...extra,
  })

  const planM = useMutation({
    mutationFn: (extra) => supplyApi.isrFulfilment(body(extra)).then(r => r.data),
    onMutate: () => setError(''),
    onSuccess: (d) => setPlan(d),
    onError: (e) => setError(e?.response?.data?.detail || 'تعذّر قراءة الطلبات'),
  })
  const exportM = useMutation({
    mutationFn: () => supplyApi.isrFulfilmentExport(body()),
    onMutate: () => setExportErr(''),
    onSuccess: (res) => {
      const cd = res.headers?.['content-disposition'] || ''
      const m = cd.match(/filename="?([^"]+)"?/)
      downloadBlob(res.data, m ? m[1] : 'isr_fulfillment.xlsx')
    },
    onError: async (e) => setExportErr(await blobErr(e)),
  })

  const busy = planM.isPending
  const submit = (e) => { e?.preventDefault(); planM.mutate({}) }
  const selected = splitIsrs(isrText)
  const toggleIsr = (n) => setIsrText(
    (selected.includes(n) ? selected.filter(x => x !== n) : [...selected, n]).join(', '))

  return (
    <div className="space-y-4">
      <RecentPicker selected={selected} onToggle={toggleIsr} collapsed={!!plan} />
      {/* noValidate: the backend validates (0.25–12 months) and answers in Arabic —
          no browser popups blocking تحليل */}
      <form onSubmit={submit} noValidate
        className="flex flex-wrap items-end gap-3 p-3 rounded-lg border border-line bg-surface">
        <label className="flex flex-col gap-1 text-xs text-content/70 grow min-w-[16rem]">
          أرقام طلبات التوريد (افصل بمسافة أو فاصلة)
          <input value={isrText} onChange={e => setIsrText(e.target.value)} dir="ltr"
            placeholder="261609, 2615043" className={`${inputCls} font-mono`} />
        </label>
        <PlanSettings value={settings} onChange={setSettings} />
        <button type="submit" disabled={busy || !isrText.trim()} className={btnPrimary}>
          {busy ? 'جاري التحليل…' : 'تحليل'}
        </button>
        {plan && (
          <>
            <button type="button" disabled={busy} onClick={() => planM.mutate({ refresh: true })}
              className={btnGhost} title="إعادة قراءة الأرصدة الحالية من SOFTECH">
              تحديث من SOFTECH
            </button>
            <button type="button" disabled={exportM.isPending || busy} onClick={() => exportM.mutate()}
              className={btnGhost}>
              {exportM.isPending ? 'جاري التصدير…' : 'تصدير Excel'}
            </button>
          </>
        )}
      </form>

      {busy && <ProgressBar since={planM.submittedAt} label="قراءة الأرصدة من سيرفرات الفروع"
        message="سيرفر بطيء أو متوقف يُستبدل بنسخة الرئيسي تلقائياً — قد يستغرق دقيقة" />}
      {exportM.isPending && <ProgressBar since={exportM.submittedAt} label="تجهيز ملف Excel" />}

      {error && <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">{error}</div>}
      {exportErr && <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">{exportErr}</div>}

      {!plan && !busy && !error && (
        <p className="text-sm text-content/60 leading-6">
          أدخل رقم طلب توريد أو أكثر من طلبات الفروع. لكل صنف مطلوب يظهر رصيد ومعدل بيع واحتياج والحد الأقصى
          لكل فرع وللرئيسي، ثم خطة التوريد: إذا كان رصيد الرئيسي يغطي الكمية كاملة يُصرف منه وحده (شحنة واحدة)،
          وإلا فمن فائض الفروع الأخرى أولاً (الفرع المانح يحتفظ بحده الأقصى) ثم من الرئيسي، والباقي نقص يحتاج شراء.
          للقراءة فقط — لا يكتب شيئاً في SOFTECH.
        </p>
      )}

      {plan && <PlanView plan={plan} setPlan={setPlan}
        isrText={plan.isrs.map(i => i.isr).join(', ')}
        coverageChanged={settingsChanged(settings, plan)} />}
    </div>
  )
}

function RecentPicker({ selected, onToggle, collapsed }) {
  const bl = useBranchLabels()
  const [days, setDays] = useState(14)
  const [open, setOpen] = useState(true)
  const show = open && !collapsed
  const recentQ = useQuery({
    queryKey: ['isr-fulfil-recent', days],
    queryFn: () => supplyApi.isrFulfilmentRecent(days).then(r => r.data),
    enabled: show, staleTime: 60_000,
  })
  const rows = recentQ.data?.results || []
  return (
    <div className="rounded-lg border border-line">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-surface-2">
        <button type="button" onClick={() => setOpen(o => !o)} className="text-sm font-medium text-content">
          {show ? '▾' : '▸'} طلبات الفروع الأخيرة من SOFTECH
        </button>
        {selected.length > 0 && <span className="text-xs text-content/60">المختار: {selected.length}</span>}
        {show && (
          <label className="ms-auto text-xs text-content/70 flex items-center gap-1">
            آخر
            <select value={days} onChange={e => setDays(Number(e.target.value))} className={`${inputCls} py-0.5`}>
              {[3, 7, 14, 30, 60, 90].map(d => <option key={d} value={d}>{d} يوم</option>)}
            </select>
          </label>
        )}
      </div>
      {show && (
        <div className="max-h-64 overflow-y-auto">
          {recentQ.isLoading && <p className="p-3 text-sm text-content/60">جاري القراءة من SOFTECH…</p>}
          {recentQ.isError && (
            <p className="p-3 text-sm text-rose-700">
              {recentQ.error?.response?.data?.detail || 'تعذّر قراءة الطلبات'} — يمكنك كتابة الأرقام يدوياً.
            </p>)}
          {recentQ.isSuccess && rows.length === 0 && (
            <p className="p-3 text-sm text-content/60">لا توجد طلبات من الفروع في آخر {days} يوم.</p>)}
          {rows.length > 0 && (
            <table className="w-full text-sm">
              <thead className="text-xs text-content/60 sticky top-0 bg-surface">
                <tr>
                  {['', 'رقم الطلب', 'الفرع', 'التاريخ', 'الأصناف', 'الكمية', 'القيمة', 'المستخدم', 'الحالة'].map(h =>
                    <th key={h} className="px-2 py-1.5 font-medium text-center">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const on = selected.includes(r.isr)
                  return (
                    <tr key={r.isr} onClick={() => onToggle(r.isr)}
                      className={`border-t border-line text-center cursor-pointer hover:bg-surface-2 ${on ? 'bg-primary/5' : ''}`}>
                      <td className="px-2 py-1"><input type="checkbox" readOnly checked={on} /></td>
                      <td className="px-2 py-1 font-mono">{r.isr}</td>
                      <td className="px-2 py-1 whitespace-nowrap">{bl(r.branch)}{r.for_branch !== r.branch ? ` ⟶ ${bl(r.for_branch)}` : ''}</td>
                      <td className="px-2 py-1">{r.date}</td>
                      <td className="px-2 py-1">{r.lines}</td>
                      <td className="px-2 py-1">{q(r.qty)}</td>
                      <td className="px-2 py-1">{money(Math.round(r.value))}</td>
                      <td className="px-2 py-1 text-xs whitespace-nowrap">{userLabel(r.user, r.user_name)}</td>
                      <td className="px-2 py-1">
                        <Chip tone={r.approved ? 'emerald' : 'amber'}>{r.approved ? 'معتمد' : 'غير معتمد'}</Chip>
                        {r.ours && <Chip tone="violet" title="طلب أنشأه النظام">من النظام</Chip>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

export function PlanView({ plan, setPlan, isrText, coverageChanged }) {
  const bl = useBranchLabels()
  const t = plan.totals
  return (
    <div className="space-y-4">
      <div className="text-xs text-content/60 flex flex-wrap gap-x-4 gap-y-1">
        <span>الأرصدة من SOFTECH: {plan.taken_at?.replace('T', ' ')}</span>
        <span>معدلات البيع: تشغيل المحرك #{plan.run_id}</span>
        <span>تغطية الطالب: {plan.fill_coverage} شهر</span>
        <span>الكمية التي تُوزَّع: {plan.plan_label}</span>
        <span>تغطية المانحين: {plan.coverage} شهر</span>
        {plan.transit_days != null && (
          <span title="تحويلات بين الفروع صُرفت ولم تُستلم — نفس قاعدة محرك الاحتياج">
            بالطريق: تحويلات آخر {plan.transit_days} يوماً لم تُستلم</span>)}
        {coverageChanged && <span className="text-amber-700">غيّرت الإعدادات — اضغط «تحليل» لإعادة الحساب</span>}
      </div>
      {plan.notices?.length > 0 && (
        <div role="alert" className="text-sm font-medium text-amber-900 bg-amber-50 border border-amber-300 rounded p-2.5 space-y-1">
          {plan.notices.map(m => <div key={m}>{m}</div>)}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead className="bg-surface-2 text-content/70 text-xs">
            <tr>
              {['الطلب', 'الفرع', 'الأصناف', 'المطلوب', 'الموصى بها', plan.plan_label, 'من فائض الفروع', 'من الرئيسي', 'نقص (شراء)',
                'مغطى من الفروع', 'مغطى بالكامل', 'يتجاوز الحد', 'قيمة المنقول', 'قيمة النقص'].map(h =>
                <th key={h} className="px-2 py-2 text-center font-medium whitespace-nowrap">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {plan.isrs.map(r => (
              <tr key={r.isr} className="border-t border-line text-center">
                <td className="px-2 py-1.5 font-mono">{r.isr}</td>
                <td className="px-2 py-1.5">{r.branch} <span className="text-content/50 text-xs">{r.branch_name || bl.nameOf(r.branch)}</span></td>
                <td className="px-2 py-1.5">{r.totals.items}</td>
                <td className="px-2 py-1.5">{q(r.totals.requested)}</td>
                <td className="px-2 py-1.5">{q(r.totals.recommended)}</td>
                <td className="px-2 py-1.5 font-semibold">{q(r.totals.planned)}</td>
                <td className="px-2 py-1.5" title={Object.entries(r.from_by_donor).map(([b, v]) => `${bl(b)}: ${q(v)}`).join(' · ')}>
                  {q(r.totals.from_branches)}
                  {Object.keys(r.from_by_donor).length > 0 && (
                    <div className="text-[11px] text-content/50">
                      {Object.entries(r.from_by_donor).map(([b, v]) => `${bl(b)}: ${q(v)}`).join(' · ')}
                    </div>)}
                </td>
                <td className="px-2 py-1.5">{q(r.totals.from_hq)}</td>
                <td className="px-2 py-1.5 font-semibold text-rose-700">{q(r.totals.shortage)}</td>
                <td className="px-2 py-1.5">{r.totals.full_branches} / {r.totals.items}</td>
                <td className="px-2 py-1.5">{r.totals.full_all} / {r.totals.items}</td>
                <td className="px-2 py-1.5">{r.totals.over_ceiling}</td>
                <td className="px-2 py-1.5">{money(Math.round(r.totals.value_branches))}</td>
                <td className="px-2 py-1.5">{money(Math.round(r.totals.value_shortage))}</td>
              </tr>
            ))}
            {plan.isrs.length > 1 && (
              <tr className="border-t border-line text-center font-semibold bg-surface-2">
                <td className="px-2 py-1.5" colSpan={2}>الإجمالي</td>
                <td className="px-2 py-1.5">{t.items}</td>
                <td className="px-2 py-1.5">{q(t.requested)}</td>
                <td className="px-2 py-1.5">{q(t.recommended)}</td>
                <td className="px-2 py-1.5">{q(t.planned)}</td>
                <td className="px-2 py-1.5">{q(t.from_branches)}</td>
                <td className="px-2 py-1.5">{q(t.from_hq)}</td>
                <td className="px-2 py-1.5 text-rose-700">{q(t.shortage)}</td>
                <td className="px-2 py-1.5">{t.full_branches} / {t.items}</td>
                <td className="px-2 py-1.5">{t.full_all} / {t.items}</td>
                <td className="px-2 py-1.5">{t.over_ceiling}</td>
                <td className="px-2 py-1.5">{money(Math.round(t.value_branches))}</td>
                <td className="px-2 py-1.5">{money(Math.round(t.value_shortage))}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {plan.isrs.map(r => (
        <IsrSection key={r.isr} r={r} returns={plan.returns?.[r.isr] || []} canWrite={!!plan.can_write} planLabel={plan.plan_label}
          fallback={plan.fallback || {}}
          isrText={isrText} settings={planBody(plan)} setPlan={setPlan} />
      ))}
    </div>
  )
}

// Donor excess → HQ return proposals for one ISR. PG only: they land in the ISR tab as
// «مقترح» and reach SOFTECH only through the usual اعتماد → ترحيل there.
function ReturnsBar({ r, returns, canWrite, isrText, settings, setPlan }) {
  const bl = useBranchLabels()
  const [, setParams] = useSearchParams()
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')
  const live = new Set(returns.filter(x => ['proposed', 'approved', 'pushed'].includes(x.status)).map(x => x.donor))
  const pending = Object.entries(r.from_by_donor).filter(([b]) => !live.has(b))
  const pendingQty = pending.reduce((s, [, v]) => s + v, 0)
  const createM = useMutation({
    mutationFn: () => supplyApi.isrFulfilmentProposals({ isrs: isrText, ...settings, isr: r.isr }).then(res => res.data),
    onMutate: () => setMsg(''),
    onSuccess: (d) => {
      setPlan(d.plan)
      qc.invalidateQueries({ queryKey: ['isr-pushes'] })
      const made = d.created.map(c => `فرع ${bl(c.donor)}: ${q(c.qty)} (#${c.id})`).join(' · ')
      setMsg(d.created.length
        ? `تم إنشاء ${d.created.length} مقترح إرجاع — ${made}. راجعها واعتمدها في تبويب طلبات التوريد.`
        : 'لم يُنشأ شيء — لا يوجد فائض جديد بعد إعادة قراءة الأرصدة، أو المقترحات موجودة بالفعل.')
    },
    onError: (e) => setMsg(e?.response?.data?.detail || 'تعذّر إنشاء المقترحات'),
  })
  if (!returns.length && !pending.length) return null
  return (
    <div className="px-3 py-2 border-b border-line flex flex-wrap items-center gap-2 text-xs">
      <span className="text-content/70">إرجاع فائض الفروع إلى الرئيسي:</span>
      {returns.map(x => (
        <Chip key={x.id} tone={RETURN_TONE[x.status] || 'gray'}
          title={x.isrdocnumber ? `SOFTECH ISR ${x.isrdocnumber}` : ''}>
          فرع {bl(x.donor)} ⟶ {bl('100')} · {q(x.qty)} · #{x.id} {x.status_label}
        </Chip>
      ))}
      {pending.length > 0 && canWrite && (
        <button onClick={() => createM.mutate()} disabled={createM.isPending} className={btnPrimary}
          title="ينشئ طلب توريد مقترح من كل فرع مانح إلى الرئيسي بالكمية المخططة؛ الرئيسي يصرف الطلب الأصلي بإذن الصرف">
          {createM.isPending ? 'جاري الإنشاء…'
            : `إنشاء مقترحات الإرجاع (${q(pendingQty)} من ${pending.length} فرع)`}
        </button>
      )}
      {pending.length > 0 && !canWrite && <span className="text-content/50">يتطلب صلاحية التوريد لإنشاء المقترحات</span>}
      {returns.length > 0 && (
        <button onClick={() => setParams(p => { const n = new URLSearchParams(p); n.set('tab', 'isr'); return n })}
          className="text-primary underline">فتح تبويب طلبات التوريد</button>
      )}
      {msg && <span className="basis-full text-content/80">{msg}</span>}
    </div>
  )
}

function IsrSection({ r, returns, canWrite, isrText, settings, setPlan, fallback, planLabel }) {
  const bl = useBranchLabels()
  const [filter, setFilter] = useState('all')
  const [open, setOpen] = useState(() => new Set())
  const counts = useMemo(() => ({
    all: r.lines.length,
    short: r.lines.filter(l => l.shortage > 0).length,
    by_branches: r.lines.filter(l => l.full_by_branches).length,
    full: r.lines.filter(l => l.full_overall).length,
    over: r.lines.filter(l => l.req.over_ceiling).length,
  }), [r])
  const lines = r.lines.filter(l =>
    filter === 'short' ? l.shortage > 0
      : filter === 'by_branches' ? l.full_by_branches
        : filter === 'full' ? l.full_overall
          : filter === 'over' ? l.req.over_ceiling : true)
  const toggle = (code) => setOpen(s => { const n = new Set(s); n.has(code) ? n.delete(code) : n.add(code); return n })

  return (
    <section className="rounded-lg border border-line">
      <header className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-line bg-surface-2">
        <h3 className="font-semibold text-content">طلب {r.isr} — فرع {r.branch} {r.branch_name || bl.nameOf(r.branch)}</h3>
        {r.kind === 'whatsapp'
          ? <Chip tone="teal">طلب واتساب</Chip>
          : <Chip tone={r.approved ? 'emerald' : 'amber'}>{r.approved ? 'معتمد في SOFTECH' : 'غير معتمد'}</Chip>}
        {r.requester_from_hq_copy && (
          <Chip tone="amber" title="سيرفر الفرع غير متاح — الرصيد من نسخة الرئيسي">
            ⚠ رصيد الفرع من آخر نسخة متزامنة على الرئيسي{r.requester_copy_at ? ` · آخر حركة ${r.requester_copy_at}` : ''}
          </Chip>
        )}
        <span className="text-xs text-content/60">{r.date} · قيمة الطلب {money(Math.round(r.value))} ج · المستخدم {userLabel(r.user, r.user_name)}</span>
        <div className="flex gap-1 ms-auto flex-wrap">
          {FILTERS.map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)}
              className={`text-xs px-2 py-1 rounded border ${filter === k
                ? 'border-primary text-primary bg-primary/5' : 'border-line text-content/70'}`}>
              {l} ({counts[k]})
            </button>
          ))}
        </div>
      </header>
      {/* return legs serve an approved SOFTECH ISR — a WhatsApp request has none yet */}
      {r.kind !== 'whatsapp' && (
        <ReturnsBar r={r} returns={returns} canWrite={canWrite} isrText={isrText} settings={settings} setPlan={setPlan} />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-content/70 text-xs">
            <tr className="border-b border-line">
              <th className="px-2 py-2 text-start font-medium">الصنف</th>
              <th className="px-2 py-2 font-medium">المطلوب</th>
              <th className="px-2 py-2 font-medium" title="تغطية الطالب × معدل بيعه − رصيده − بالطريق؛ موجب → مقرّب لأعلى (عبوة على الأقل)، وإلا صفر">الموصى بها</th>
              <th className="px-2 py-2 font-medium" title="الكمية التي تُوزَّع على الفروع / الرئيسي / النقص">{planLabel}</th>
              <th className="px-2 py-2 font-medium" title="رصيد الفرع الطالب الحالي">رصيد الطالب</th>
              <th className="px-2 py-2 font-medium">معدل البيع</th>
              <th className="px-2 py-2 font-medium">الحد الأقصى</th>
              <th className="px-2 py-2 font-medium">بعد التوريد</th>
              <th className="px-2 py-2 font-medium" title="فائض الفروع الأخرى فوق حدها الأقصى">فائض الفروع</th>
              <th className="px-2 py-2 font-medium">من الفروع</th>
              <th className="px-2 py-2 font-medium">رصيد الرئيسي</th>
              <th className="px-2 py-2 font-medium">من الرئيسي</th>
              <th className="px-2 py-2 font-medium">نقص</th>
              <th className="px-2 py-2 font-medium" title="معدل بيع كل الفروع / شهور تغطية رصيد الفروع">الشبكة</th>
              <th className="px-2 py-2 font-medium">قيمة النقص</th>
            </tr>
          </thead>
          <tbody>
            {lines.map(l => {
              const gives = l.donors.filter(d => d.give > 0)
              const isOpen = open.has(l.code)
              return (
                <Fragment key={l.code}>
                  <tr onClick={() => toggle(l.code)}
                    className={`border-b border-line text-center cursor-pointer hover:bg-surface-2 ${isOpen ? 'bg-surface-2' : ''}`}>
                    <td className="px-2 py-1.5 text-start">
                      <span className="text-content/40 me-1">{isOpen ? '▾' : '▸'}</span>
                      <span className="font-mono text-xs text-content/60 me-1">{l.code}</span>{l.name}
                    </td>
                    <td className="px-2 py-1.5">{q(l.qty)}</td>
                    <td className="px-2 py-1.5" title={l.no_sales ? 'الفرع لا يبيع هذا الصنف — الموصى بها = المطلوبة' : `حتى ${q(l.fill_ceiling)} (${q(l.req.rate)}/شهر)`}>
                      {q(l.recommended)}
                      {l.no_sales && <div><Chip tone="gray">بلا مبيعات</Chip></div>}
                    </td>
                    <td className={`px-2 py-1.5 font-semibold ${l.plan_qty !== l.qty ? 'text-primary' : ''}`}>{q(l.plan_qty)}</td>
                    <td className="px-2 py-1.5">
                      {q(l.req.stock)}
                      {l.req.transit > 0 && (
                        <div className="text-[11px] text-sky-700" title="تحويلات صُرفت للفرع ولم تُستلم بعد — محسوبة مع الرصيد">
                          + بالطريق {q(l.req.transit)}</div>)}
                    </td>
                    <td className="px-2 py-1.5">{q(l.req.rate)}</td>
                    <td className="px-2 py-1.5">{q(l.req.ceiling)}</td>
                    <td className="px-2 py-1.5">
                      {q(l.req.after)}
                      {l.req.over_ceiling && <Chip tone="amber" title="الرصيد بعد التوريد أعلى من الحد الأقصى للفرع">فوق الحد</Chip>}
                    </td>
                    <td className="px-2 py-1.5">{q(l.network.excess)}</td>
                    <td className="px-2 py-1.5">
                      {q(l.from_branches)}
                      {gives.length > 0 && (
                        <div className="text-[11px] text-content/50">{gives.map(d => `${bl(d.branch)}: ${q(d.give)}`).join(' · ')}</div>)}
                    </td>
                    <td className="px-2 py-1.5">{q(l.hq_stock)}</td>
                    <td className="px-2 py-1.5">
                      {q(l.from_hq)}
                      {l.hq_first && <div><Chip tone="emerald" title="رصيد الرئيسي يغطي الطلب كاملاً — شحنة واحدة بلا تحويل من الفروع">الرئيسي يكفي</Chip></div>}
                    </td>
                    <td className={`px-2 py-1.5 font-semibold ${l.shortage > 0 ? 'text-rose-700' : 'text-emerald-700'}`}>
                      {l.shortage > 0 ? q(l.shortage) : '✓'}
                    </td>
                    <td className="px-2 py-1.5 text-xs text-content/70">
                      {q(l.network.rate)} / {l.network.months == null ? '—' : `${q(l.network.months)} ش`}
                    </td>
                    <td className="px-2 py-1.5">{l.value_shortage ? money(Math.round(l.value_shortage)) : '—'}</td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-line bg-surface-2/50">
                      <td colSpan={15} className="px-3 py-2"><BranchDetail l={l} reqBranch={r.branch} fallback={fallback} /></td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {lines.length === 0 && (
              <tr><td colSpan={15} className="px-3 py-4 text-center text-content/50">لا أصناف في هذا التصنيف.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function BranchDetail({ l, reqBranch, fallback = {} }) {
  const bl = useBranchLabels()
  // branches whose stock came from server 100's synced copy (their server was down)
  const tag = (b) => (b in fallback ? ' · نسخة الرئيسي' : '')
  const rows = [
    { branch: reqBranch, label: `${bl(reqBranch)} (الطالب)${tag(reqBranch)}`, stock: l.req.stock,
      transit: l.req.transit, rate: l.req.rate,
      need: l.req.need, ceiling: l.req.ceiling, excess: null, give: null, req: true },
    // same order as the Excel: the requesting branch first, then the others by code (130, 140 …)
    ...[...l.donors].sort((a, b) => Number(a.branch) - Number(b.branch))
      .map(d => ({ ...d, label: `${bl(d.branch)}${tag(d.branch)}` })),
  ]
  return (
    <table className="text-xs">
      <thead className="text-content/60">
        <tr>
          {['الفرع', 'الرصيد', 'بالطريق', 'معدل البيع', 'الاحتياج', 'الحد الأقصى', 'فائض قابل للنقل', 'يعطي'].map(h =>
            <th key={h} className="px-3 py-1 font-medium text-center">{h}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map(d => (
          <tr key={d.branch} className={d.req ? 'font-semibold' : ''}>
            <td className="px-3 py-0.5 text-start whitespace-nowrap">{d.label}</td>
            <td className="px-3 py-0.5 text-center">{q(d.stock)}</td>
            <td className="px-3 py-0.5 text-center text-sky-700">{d.transit ? q(d.transit) : ''}</td>
            <td className="px-3 py-0.5 text-center">{q(d.rate)}</td>
            <td className="px-3 py-0.5 text-center">{q(d.need)}</td>
            <td className="px-3 py-0.5 text-center">{q(d.ceiling)}</td>
            <td className="px-3 py-0.5 text-center">{d.excess == null ? '' : q(d.excess)}</td>
            <td className="px-3 py-0.5 text-center text-primary">{d.give ? q(d.give) : ''}</td>
          </tr>
        ))}
        <tr className="border-t border-line">
          <td className="px-3 py-0.5 text-center">الرئيسي 100</td>
          <td className="px-3 py-0.5 text-center">{q(l.hq_stock)}</td>
          <td colSpan={4} />
          <td className="px-3 py-0.5 text-center text-primary">{l.from_hq ? q(l.from_hq) : ''}</td>
        </tr>
      </tbody>
    </table>
  )
}
