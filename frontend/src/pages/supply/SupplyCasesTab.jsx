/**
 * SupplyCasesTab.jsx — «متابعة النواقص»: the daily follow-up queue (doc 24 §15/§16/§19).
 *
 * Every unresolved need is a durable case that carries over across days. The queue is
 * ordered by the backend (urgent → scarcity → oldest → biggest gap). A case shows WHY the
 * engine recommends what it does (the quantity ledger + reasons) and lets the operator act:
 * approve the internal transfer (→ DRAFT transfer request for the transfers team), order the
 * residual (→ order list), or move the case along. The server validates every action.
 */
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import OrderPanel from './OrderPanel'
import { CASE_STATUS_TONE, Chip, TRANSITION_LABEL, btnGhost, btnPrimary, errText, fmtDate,
         inputCls, newKey, q } from './supplyUi'

const BUCKETS = [
  ['', 'كل المفتوح', 'total'], ['urgent', 'عاجل', 'urgent'], ['zero_stock', 'رصيد صفر', 'zero_stock'],
  ['customer_waiting', 'عملاء منتظرون', 'customer_waiting'],
  ['availability_found', 'عرض مورد لم يُنفَّذ', 'availability_found'],
  ['awaiting_decision', 'بانتظار قرار', 'awaiting_decision'],
  ['transfer_pending', 'تحويل قيد التنفيذ', 'transfer_pending'], ['ordered', 'تم الطلب', 'ordered'],
  ['partially_fulfilled', 'مُلبّى جزئياً', 'partially_fulfilled'], ['searching', 'جارٍ البحث', 'searching'],
  ['overdue', 'متأخر +3 أيام', 'overdue'],
]

const LEDGER_ROWS = [
  ['required', 'الاحتياج الصافي', true], ['gross_requirement', 'الاحتياج قبل خصم ما هو قيد التنفيذ'],
  ['calculated_demand', 'فجوة محرك الطلب'], ['ledger_demand', 'طلبات مسجّلة (بعد منع الازدواج)'],
  ['customer_demand', 'عملاء منتظرون'], ['branch_request', 'طلبات الفرع'],
  ['current_stock', 'الرصيد الحالي'], ['confirmed_incoming', 'بالطريق (محسوب ضمن الفجوة)'],
  ['pending_internal_in', 'تحويلات واردة مفتوحة'], ['pending_orders', 'طلبات شراء مفتوحة'],
  ['transferable_surplus', 'فائض داخلي متاح'], ['internally_allocated', 'تغطية داخلية مقترحة'],
  ['residual_gap', 'فجوة الشراء الخارجي', true], ['approved_purchase', 'مشتريات معتمدة'],
]

const RECEIPT_LABEL = { open: 'بانتظار الاستلام', received: 'تم الاستلام', cancelled: 'ملغى' }

function rows(data) { return Array.isArray(data) ? data : (data?.results || []) }

export default function SupplyCasesTab() {
  const qc = useQueryClient()
  const [params] = useSearchParams()
  // ?bucket= deep link (e.g. from the dashboard KPI cards)
  const [bucket, setBucket] = useState(() => {
    const b = params.get('bucket') || ''
    return BUCKETS.some(([k]) => k === b) ? b : ''
  })
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)

  const summaryQ = useQuery({ queryKey: ['supply-cases-summary'],
    queryFn: () => supplyApi.casesSummary().then(r => r.data) })
  const listQ = useQuery({ queryKey: ['supply-cases', bucket, page],
    queryFn: () => supplyApi.cases({ bucket: bucket || undefined, page }).then(r => r.data),
    placeholderData: prev => prev })

  const sweepM = useMutation({
    mutationFn: () => supplyApi.casesSweep().then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['supply-cases'] })
                       qc.invalidateQueries({ queryKey: ['supply-cases-summary'] }) },
  })

  const list = rows(listQ.data)
  const total = listQ.data?.count ?? list.length
  const s = summaryQ.data || {}

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {BUCKETS.map(([k, l, sk]) => (
          <button key={k || 'all'} type="button" onClick={() => { setBucket(k); setPage(1); setSelected(null) }}
            className={`text-xs px-2.5 py-1 rounded-full border transition ${bucket === k
              ? 'border-primary bg-primary text-white' : 'border-line bg-surface text-content/70 hover:border-primary/50'}`}>
            {l} <span className="opacity-70">{s[sk] ?? 0}</span>
          </button>
        ))}
        <button type="button" onClick={() => sweepM.mutate()} disabled={sweepM.isPending}
          className={`${btnGhost} text-xs mr-auto`}
          title="يحدّث إشارات الطلب ثم يقيّم كل الحالات الآن (يعمل تلقائياً يومياً 08:00)">
          {sweepM.isPending ? 'جارٍ التقييم…' : '↻ تقييم الآن'}
        </button>
      </div>
      {sweepM.data && (
        <div className="text-xs text-content/60">
          فُتحت {sweepM.data.opened} · حُدّثت {sweepM.data.updated} · أُغلقت {sweepM.data.closed}
          {sweepM.data.errors ? ` · أخطاء ${sweepM.data.errors}` : ''}
        </div>)}
      {sweepM.isError && <div className="text-xs text-rose-600">{errText(sweepM.error)}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,30rem)] gap-4">
        <div className="rounded-lg border border-line bg-surface overflow-x-auto min-w-0">
          <table className="w-full text-sm">
            <thead className="text-[11px] text-content/60 border-b border-line bg-primary/5">
              <tr>
                <th className="text-right py-2 px-2">الصنف</th>
                <th className="text-right py-2 px-2">الفرع</th>
                <th className="text-right py-2 px-2">الحالة</th>
                <th className="py-2 px-2">الاحتياج</th>
                <th className="py-2 px-2">للشراء</th>
                <th className="py-2 px-2">داخلي</th>
                <th className="py-2 px-2">منتظرون</th>
                <th className="py-2 px-2">الرصيد</th>
                <th className="py-2 px-2">أيام</th>
              </tr>
            </thead>
            <tbody>
              {listQ.isLoading && <tr><td colSpan={9} className="text-center py-6 text-content/50">جارٍ التحميل…</td></tr>}
              {!listQ.isLoading && list.length === 0 && (
                <tr><td colSpan={9} className="text-center py-6 text-content/50">لا توجد حالات هنا 👌</td></tr>)}
              {list.map(c => (
                <tr key={c.id} onClick={() => setSelected(c.id)}
                  className={`border-b border-line/60 cursor-pointer ${selected === c.id ? 'bg-primary/10' : 'hover:bg-primary/5'}`}>
                  <td className="py-1.5 px-2">
                    <div className="flex items-center gap-1.5">
                      {c.is_urgent && <span title="عاجل" className="w-2 h-2 rounded-full bg-rose-500 shrink-0" />}
                      <span className="truncate text-content" title={c.item_name}>{c.item_name}</span>
                      {c.has_availability && <span title="يوجد عرض مورد">📦</span>}
                    </div>
                    <div className="text-[11px] text-content/50">{c.item_softech_id}</div>
                  </td>
                  <td className="py-1.5 px-2 text-content/80">{c.branch_name}</td>
                  <td className="py-1.5 px-2"><Chip tone={CASE_STATUS_TONE[c.status]}>{c.status_display}</Chip></td>
                  <td className="py-1.5 px-2 text-center">{q(c.required_qty)}</td>
                  <td className="py-1.5 px-2 text-center font-bold text-primary">{q(c.residual_gap)}</td>
                  <td className="py-1.5 px-2 text-center">{Number(c.internal_cover) ? q(c.internal_cover) : '—'}</td>
                  <td className="py-1.5 px-2 text-center">{Number(c.customer_demand) ? q(c.customer_demand) : '—'}</td>
                  <td className="py-1.5 px-2 text-center">{q(c.current_stock)}</td>
                  <td className={`py-1.5 px-2 text-center ${c.days_open >= 3 ? 'text-rose-600 font-medium' : ''}`}>{c.days_open}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {total > list.length && (
            <div className="flex items-center gap-2 p-2 text-xs text-content/60 border-t border-line">
              <span>صفحة {page}</span>
              <button type="button" disabled={page === 1} onClick={() => setPage(p => p - 1)}
                className="hover:text-primary disabled:opacity-40">السابق</button>
              <button type="button" disabled={!listQ.data?.next} onClick={() => setPage(p => p + 1)}
                className="hover:text-primary disabled:opacity-40">التالي</button>
              <span className="mr-auto">{total} حالة</span>
            </div>
          )}
        </div>

        <div className="min-w-0">
          {selected
            ? <CaseDetail key={selected} id={selected} onChanged={() => {
                qc.invalidateQueries({ queryKey: ['supply-cases'] })
                qc.invalidateQueries({ queryKey: ['supply-cases-summary'] }) }} />
            : <div className="text-sm text-content/50 p-4">اختر حالة لعرض سبب التوصية والإجراءات.</div>}
        </div>
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════

function CaseDetail({ id, onChanged }) {
  const qc = useQueryClient()
  const [planOpen, setPlanOpen] = useState(false)
  const [approveKey] = useState(newKey)            // one key per opened case → safe re-clicks
  const [reason, setReason] = useState('')
  const [pendingStatus, setPendingStatus] = useState(null)
  const [ordering, setOrdering] = useState(false)

  const caseQ = useQuery({ queryKey: ['supply-case', id], queryFn: () => supplyApi.caseGet(id).then(r => r.data) })
  const recQ = useQuery({ queryKey: ['supply-case-rec', id], enabled: planOpen,
    queryFn: () => supplyApi.caseRec(id).then(r => r.data) })
  const decQ = useQuery({ queryKey: ['supply-decisions', id],
    queryFn: () => supplyApi.decisions({ case: id }).then(r => r.data) })

  const changed = () => {
    qc.invalidateQueries({ queryKey: ['supply-case', id] })
    qc.invalidateQueries({ queryKey: ['supply-case-rec', id] })
    qc.invalidateQueries({ queryKey: ['supply-decisions', id] })
    onChanged?.()
  }
  const evaluateM = useMutation({ mutationFn: () => supplyApi.caseEvaluate(id), onSuccess: changed })
  const transitionM = useMutation({
    mutationFn: ({ status, reason: r }) => supplyApi.caseTransition(id, status, r),
    onSuccess: () => { setPendingStatus(null); setReason(''); changed() } })
  const approveM = useMutation({
    mutationFn: () => supplyApi.caseApproveTransfer(id, { idempotency_key: approveKey }).then(r => r.data),
    onSuccess: () => { setPlanOpen(false); changed() } })

  if (caseQ.isLoading) return <div className="text-sm text-content/50 p-4">جارٍ التحميل…</div>
  if (caseQ.isError) return <div className="text-sm text-rose-600 p-4">{errText(caseQ.error)}</div>
  const c = caseQ.data
  const L = c.last_ledger || {}
  const open = !['fulfilled', 'cancelled'].includes(c.status)
  const failedDrafts = (c.transfer_requests || []).filter(t => ['rejected', 'cancelled'].includes(t.status))

  return (
    <div className="rounded-lg border border-line bg-surface p-3 space-y-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0">
          <div className="font-bold text-content truncate">{c.item_name}</div>
          <div className="text-xs text-content/60">{c.item_softech_id} · {c.branch_name} · منذ {c.days_open} يوم</div>
        </div>
        <div className="mr-auto flex flex-col items-end gap-1">
          <Chip tone={CASE_STATUS_TONE[c.status]}>{c.status_display}</Chip>
          {c.is_urgent && <Chip tone="rose">عاجل · ندرة {c.scarcity_score}</Chip>}
        </div>
      </div>

      {/* Why — the quantity ledger (every number from the engine) */}
      <table className="w-full text-xs">
        <tbody>
          {LEDGER_ROWS.filter(([k, , strong]) => strong || (L[k] !== null && L[k] !== undefined && Number(L[k]) !== 0))
            .map(([k, label, strong]) => (
              <tr key={k} className="border-b border-line/50">
                <td className={`py-1 ${strong ? 'font-bold text-content' : 'text-content/70'}`}>{label}</td>
                <td className={`py-1 text-left ${strong ? 'font-bold text-primary' : 'text-content'}`}>{q(L[k])}</td>
              </tr>))}
        </tbody>
      </table>
      {c.last_reasons?.length > 0 && (
        <ul className="text-xs text-content/80 list-disc pr-5 space-y-0.5">
          {c.last_reasons.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      )}
      <div className="text-[11px] text-content/50">آخر تقييم: {fmtDate(c.last_evaluated_at)}</div>

      {/* Draft transfers created from this case — live status */}
      {c.transfer_requests?.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs text-content/60">مسودات التحويل</div>
          {c.transfer_requests.map(t => (
            <Link key={t.id} to={`/transfers/${t.id}`} className="flex items-center gap-2 text-xs hover:text-primary">
              <span className="font-mono">{t.request_number}</span>
              <span className="text-content/60">من {t.supplying_branch}</span>
              <Chip tone={['rejected', 'cancelled'].includes(t.status) ? 'rose' : t.status === 'completed' ? 'emerald' : 'indigo'}>
                {t.status_label}</Chip>
            </Link>
          ))}
          {failedDrafts.length > 0 && open && (
            <div className="text-xs text-rose-700">
              رُفضت/أُلغيت مسودة — الفائض المحجوز أُفرج عنه. أعد التقييم ثم اختر إجراءً آخر.
            </div>)}
        </div>
      )}

      {/* Actions */}
      {open && (
        <div className="space-y-2 border-t border-line pt-3">
          <div className="flex flex-wrap gap-2">
            {Number(c.internal_cover) > 0 && c.branch && (
              <button type="button" className={btnPrimary} onClick={() => setPlanOpen(v => !v)}>
                اعتماد التحويل الداخلي ({q(c.internal_cover)})
              </button>)}
            {Number(c.residual_gap) > 0 && (
              <button type="button" className={btnGhost} onClick={() => setOrdering(true)}>
                طلب شراء ({q(Math.ceil(Number(c.residual_gap) - 1e-9))})
              </button>)}
            <button type="button" className={btnGhost} onClick={() => evaluateM.mutate()} disabled={evaluateM.isPending}>
              {evaluateM.isPending ? '…' : '↻ إعادة التقييم'}
            </button>
          </div>

          {planOpen && (
            <div className="rounded border border-primary/40 p-2 space-y-2">
              <div className="text-xs text-content/70">
                سيُنشأ <b>طلب تحويل (مسودة)</b> لكل فرع مصدر — يقدّمه ويعتمده فريق التحويلات في المسار المعتاد.
                الكميات تُعاد مراجعتها على الرصيد الحي لحظة الاعتماد.
              </div>
              {recQ.isLoading && <div className="text-xs text-content/50">جارٍ حساب الخطة الحالية…</div>}
              {recQ.data?.allocation?.transfers?.map(t => (
                <div key={t.from_branch_id} className="text-xs flex justify-between gap-2">
                  <span>{t.from_branch_name}: <b>{q(t.qty)}</b></span>
                  <span className="text-content/50">{t.reason}</span>
                </div>
              ))}
              {recQ.data && !recQ.data.allocation?.transfers?.length && (
                <div className="text-xs text-amber-700">لا يوجد فائض قابل للتحويل الآن.</div>)}
              <div className="flex gap-2">
                <button type="button" className={btnPrimary} onClick={() => approveM.mutate()}
                  disabled={approveM.isPending || !recQ.data?.allocation?.transfers?.length}>
                  {approveM.isPending ? 'جارٍ الإنشاء…' : 'تأكيد وإنشاء المسودة'}
                </button>
                <button type="button" className="text-xs text-content/50" onClick={() => setPlanOpen(false)}>إلغاء</button>
              </div>
              {approveM.isError && <div className="text-xs text-rose-600">{errText(approveM.error)}</div>}
            </div>
          )}
          {approveM.data && (
            <div className="text-xs text-emerald-700">
              ✓ أُنشئت {approveM.data.transfer_requests.map(t => t.request_number).join('، ')}
              {approveM.data.replayed ? ' (مسجّلة سابقاً)' : ''}
            </div>)}

          {/* Status moves (server validates the transition map) */}
          {c.allowed_transitions?.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-content/50">نقل الحالة:</span>
              {c.allowed_transitions.map(s => (
                <button key={s} type="button"
                  onClick={() => (s === 'cancelled' ? setPendingStatus(s) : transitionM.mutate({ status: s, reason: '' }))}
                  className={`text-[11px] px-2 py-0.5 rounded border ${s === 'cancelled'
                    ? 'border-rose-200 text-rose-700' : 'border-line text-content/80 hover:border-primary'}`}>
                  {TRANSITION_LABEL[s] || s}
                </button>
              ))}
            </div>
          )}
          {pendingStatus === 'cancelled' && (
            <div className="flex gap-2">
              <input value={reason} onChange={e => setReason(e.target.value)} placeholder="سبب الإلغاء (مطلوب)"
                className={`${inputCls} text-xs flex-1`} />
              <button type="button" className={btnPrimary} disabled={!reason.trim() || transitionM.isPending}
                onClick={() => transitionM.mutate({ status: 'cancelled', reason })}>تأكيد</button>
            </div>
          )}
          {(transitionM.isError || evaluateM.isError) && (
            <div className="text-xs text-rose-600">{errText(transitionM.error || evaluateM.error)}</div>)}
        </div>
      )}
      {!open && c.close_reason && <div className="text-xs text-content/60">سبب الإغلاق: {c.close_reason}</div>}

      {ordering && (
        <OrderPanel
          lines={[{ key: c.id, item_id: c.item, case_id: c.id, branch_id: c.branch,
                    // orders go out in whole units (you can't buy 3.67 boxes)
                    qty: Math.ceil(Number(c.residual_gap) - 1e-9), label: `${c.item_name} (${c.item_softech_id})` }]}
          onClose={() => setOrdering(false)} onCommitted={changed} />
      )}

      {/* Recommended vs decided (§40) */}
      {rows(decQ.data).length > 0 && (
        <div className="border-t border-line pt-2 space-y-1">
          <div className="text-xs text-content/60">القرارات (الموصى به ← المعتمد)</div>
          {rows(decQ.data).map(d => (
            <div key={d.id} className="text-xs flex flex-wrap gap-x-2">
              <span>{d.kind_display}</span>
              <span>{q(d.recommended_qty)} ← <b>{q(d.decided_qty)}</b></span>
              {d.is_override && <Chip tone="amber" title={d.override_reason}>تجاوز</Chip>}
              {d.receipt_status && <span className="text-content/50">{RECEIPT_LABEL[d.receipt_status] || d.receipt_status}</span>}
              <span className="text-content/50">{d.created_by_name} · {fmtDate(d.created_at)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
