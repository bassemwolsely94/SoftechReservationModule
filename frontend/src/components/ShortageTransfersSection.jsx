/**
 * ShortageTransfersSection — «إنشاء مقترحات التحويل» inside the shortage stock check (P-33 a).
 *
 * The same plan and the same two linked proposals as «طلبات واتساب» (/supply): for each donor branch,
 * a supply request donor → 100 and 100 → the requesting branch, from the donor's EXCESS after its own
 * cover (not raw stock). The server re-reads stock, refuses a second move of the same need (also when
 * the list came from a WhatsApp request) and checks the purchasing write right. Nothing reaches
 * SOFTECH here: the proposals are approved and pushed in the ISR tab.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { shortageApi } from '../api/client'
import useBranchLabels from '../hooks/useBranchLabels'
import ProgressBar from './ProgressBar'
import { PlanView, PlanSettings, DEFAULT_SETTINGS, settingsBody, planBody, settingsChanged } from '../pages/supply/IsrFulfilmentTab'

const fmt = (n) => Number(n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 2 })
const LIVE = ['proposed', 'approved', 'pushed']

export default function ShortageTransfersSection({ listId }) {
  const bl = useBranchLabels()
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [plan, setPlan] = useState(null)
  const [msg, setMsg] = useState('')
  const [since, setSince] = useState(null)
  const errOf = (e, d) => e?.response?.data?.detail || d

  const analyse = useMutation({
    mutationFn: () => { setSince(Date.now()); return shortageApi.transferPlan(listId, settingsBody(settings)).then(r => r.data) },
    onMutate: () => setMsg(''),
    onSuccess: (d) => setPlan(d),
    onError: (e) => setMsg(errOf(e, 'تعذّر تحليل التحويل')),
  })
  const create = useMutation({
    mutationFn: () => { setSince(Date.now()); return shortageApi.transfers(listId, planBody(plan)).then(r => r.data) },
    onMutate: () => setMsg(''),
    onSuccess: (d) => {
      setPlan(d.plan)
      const to = d.plan?.isrs?.[0]?.branch
      setMsg(d.created.length
        ? `تم إنشاء ${d.created.length} تحويل (${d.created.length * 2} طلب توريد مقترح): `
          + d.created.map(c => `فرع ${bl(c.donor)} ← ${bl('100')} ← فرع ${bl(to)}: ${fmt(c.qty)}`).join(' · ')
          + '. راجعها واعتمدها في «التوريد» ← «طلبات التوريد».'
        : 'لم يُنشأ شيء — لا يوجد فائض جديد بعد إعادة قراءة الأرصدة، أو التحويلات موجودة بالفعل.')
    },
    onError: (e) => setMsg(errOf(e, 'تعذّر إنشاء التحويلات')),
  })

  const r = plan?.isrs?.[0]
  const transfers = plan?.transfers || []
  const live = new Set(transfers.filter(t => t.legs.some(l => LIVE.includes(l.status))).map(t => t.donor))
  const pending = Object.entries(r?.from_by_donor || {}).filter(([b]) => !live.has(b))
  const pendingQty = pending.reduce((s, [, v]) => s + v, 0)
  const busy = analyse.isPending || create.isPending

  return (
    <div data-tour="shortage-main-transfers" className="mb-4 border border-blue-200 bg-blue-50/50 rounded-xl p-3 space-y-3">
      <div className="text-xs font-bold text-blue-800">التحويل من فائض الفروع (فرع ← الرئيسي ← الفرع الطالب)</div>
      <div className="flex flex-wrap items-end gap-3">
        <PlanSettings value={settings} onChange={setSettings} />
        <button onClick={() => analyse.mutate()} disabled={busy}
                className="px-3 py-1.5 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
          {analyse.isPending ? 'جاري التحليل…' : 'تحليل التحويل'}
        </button>
        {plan && pending.length > 0 && plan.can_transfer && (
          <button data-tour="shortage-main-transfers-create" onClick={() => create.mutate()} disabled={busy}
                  title="لكل فرع مانح: طلب توريد من الفرع إلى الرئيسي + طلب من الرئيسي إلى الفرع الطالب — من الأصناف المؤكَّدة فقط، بعد إعادة قراءة الأرصدة"
                  className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50">
            {create.isPending ? 'جاري الإنشاء…' : `إنشاء مقترحات التحويل (${fmt(pendingQty)} من ${pending.length} فرع)`}
          </button>
        )}
      </div>
      {busy && <ProgressBar label="قراءة أرصدة الفروع من SOFTECH" since={since} />}
      {plan?.via_request && (
        <div className="text-xs text-blue-800">هذه القائمة من طلب واتساب — التحويل يُسجَّل على الطلب نفسه، فلا يُنقل مرتين من الشاشتين.</div>
      )}
      {transfers.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {transfers.map(t => (
            <span key={t.donor} className="px-2 py-1 bg-white border border-gray-200 rounded-lg">
              فرع {bl(t.donor)}: {t.legs.map(l => `#${l.id} ${l.status_label}`).join(' · ')}
            </span>
          ))}
        </div>
      )}
      {msg && <div className="text-sm text-gray-800 bg-white border rounded-lg px-3 py-2">{msg}</div>}
      {plan && <PlanView plan={plan} setPlan={setPlan} isrText={r?.isr || ''} coverageChanged={settingsChanged(settings, plan)} />}
    </div>
  )
}
