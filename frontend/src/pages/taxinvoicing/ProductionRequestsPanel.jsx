/**
 * «طلبات الإنتاج» — batch S4: ETA production code requests prepared from the coding queue's decisions. Display only:
 * the server prepares each request from the item's decision, and every send goes through its gates (the production
 * switch, matrix finalize, the typed count, the first-request rule). The reasons shown here only explain a disabled
 * button; the server re-checks all of them and its refusal is shown as it comes back.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { ActionMsg, Badge, Btn, DOC_STATUS_TONE, Failed, fmtInt, fmtTime, Grid, INPUT, Loading, Notice, Section, useAction } from './ui'

export const SWITCH_OFF = 'إرسال الأكواد للمنظومة الفعلية مغلق (TAX_ETA_CODING_PRODUCTION_ENABLED)'
export const FIRST_ONLY = 'أرسل طلباً واحداً أولاً حتى تعتمده المصلحة'
const IN_FLIGHT_WAIT = 'يوجد طلب للمنظومة الفعلية لدى المصلحة لم يُعتمد بعد؛ انتظر اعتماده قبل إرسال طلب آخر'
const SENDABLE = ['prepared', 'failed']
const ASKABLE = ['submitted', 'uncertain']
const STATUS_TONE = { ...DOC_STATUS_TONE, prepared: DOC_STATUS_TONE.draft, sending: DOC_STATUS_TONE.submitting,
  failed: DOC_STATUS_TONE.rejected, cancelled: 'bg-gray-100 text-gray-500 border-gray-200', approved: DOC_STATUS_TONE.valid }

const skippedText = list => (list?.length
  ? ` — تُرك ${fmtInt(list.length)}: ${list.slice(0, 5).map(s => `${s.itemcode} (${s.why})`).join('، ')}` : '')

function CancelRequest({ row, onClose }) {
  const [reason, setReason] = useState('')
  const act = useAction()
  return (
    <div className="flex flex-wrap items-center gap-1 mt-1">
      <input className={`${INPUT} w-48`} aria-label={`سبب إلغاء ${row.itemcode}`} placeholder="سبب الإلغاء" autoFocus
        value={reason} onChange={e => setReason(e.target.value)} />
      <Btn variant="danger" className="px-2 py-1" disabled={act.pending || !reason.trim()}
        onClick={() => act.run(() => taxInvoicingApi.codeCancel(row.id, reason.trim()), 'أُلغي الطلب', onClose)}>
        تأكيد الإلغاء
      </Btn>
      <button type="button" className="text-[11px] text-gray-500" onClick={onClose}>تراجع</button>
      <ActionMsg msg={act.msg} />
    </div>
  )
}

export default function ProductionRequestsPanel({ me }) {
  const act = useAction()
  const [picked, setPicked] = useState([])
  const [typed, setTyped] = useState('')
  const [refused, setRefused] = useState([])
  const [cancelling, setCancelling] = useState(null)
  const state = useQuery({ queryKey: ['tax-invoicing', 'coding-production'],
    queryFn: () => taxInvoicingApi.codingProduction().then(r => r.data) })
  const list = useQuery({ queryKey: ['tax-invoicing', 'codes', { environment: 'production' }],
    queryFn: () => taxInvoicingApi.codes({ environment: 'production' }).then(r => r.data) })
  const s = state.data
  const rows = list.data?.rows || []
  const byId = Object.fromEntries(rows.map(r => [r.id, r]))
  const sendable = rows.filter(r => SENDABLE.includes(r.status))
  const chosen = picked.length ? sendable.filter(r => picked.includes(r.id)) : sendable
  const askable = rows.filter(r => ASKABLE.includes(r.status))
  const firstRule = s && s.first_request_pending && !s.batch_ok

  const sendBlock = (() => {
    if (!s) return '…'
    if (!s.enabled) return SWITCH_OFF
    if (!chosen.length) return 'لا توجد طلبات جاهزة للإرسال'
    if (firstRule && chosen.length > 1) return FIRST_ONLY
    if (firstRule && s.in_flight > 0) return IN_FLIGHT_WAIT
    if (typed.trim() !== String(chosen.length)) return `اكتب عدد الطلبات (${chosen.length}) للتأكيد`
    return ''
  })()

  const toggle = r => setPicked(p => (p.includes(r.id) ? p.filter(x => x !== r.id) : [...p, r.id]))
  const prepare = () => act.run(() => taxInvoicingApi.codingPrepare({ itemcodes: s.ready.itemcodes }),
    d => `جُهّز ${fmtInt(d.created.length)} طلب${skippedText(d.skipped)}`)
  const send = () => {
    setRefused([])
    act.run(() => taxInvoicingApi.codesSend({ ids: chosen.map(r => r.id), confirm: typed.trim() }),
      d => `أُرسل ${fmtInt(d.submitted)} · لم يُقبل ${fmtInt(d.failed)} · غير مؤكد ${fmtInt(d.uncertain)}${d.stopped ? ` — ${d.stopped}` : ''}`,
      d => { setRefused(d.refused || []); setPicked([]); setTyped('') })
  }
  const refresh = () => act.run(() => taxInvoicingApi.codesRefresh({ ids: askable.map(r => r.id) }),
    d => `سُئل عن ${fmtInt(d.checked)} · اعتُمد ${fmtInt(d.approved)} · رُفض ${fmtInt(d.rejected)}${d.error ? ` — ${d.error}` : ''}`)
  const gs1 = r => act.run(() => taxInvoicingApi.codingGs1({ itemcode: r.itemcode }), `جُهّز طلب GS1 للصنف ${r.itemcode}`)

  const columns = [
    { key: 'pick', label: '', sortable: false, render: r => (SENDABLE.includes(r.status) && me.can_finalize
      ? <input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r)} aria-label={`اختيار طلب ${r.itemcode}`} /> : null) },
    { key: 'itemcode', label: 'الصنف', className: 'max-w-[240px]', render: r => (
      <>
        <div className="truncate">{r.code_name_ar || r.code_name || '—'}</div>
        <div className="text-[11px] text-gray-400">{r.itemcode} · <span dir="ltr" className="font-mono">{r.item_code}</span> · {r.purpose_label}</div>
      </>
    ) },
    { key: 'status', label: 'الحالة', value: r => r.status_label, render: r => <Badge tone={STATUS_TONE[r.status]}>{r.status_label}</Badge> },
    { key: 'eta_status', label: 'حالة المصلحة', render: r => r.eta_status || '—' },
    { key: 'error', label: 'الخطأ', className: 'max-w-[260px] text-xs text-red-700', render: r => r.error || '—' },
    { key: 'prepared_at', label: 'جُهّز', type: 'date', render: r => fmtTime(r.prepared_at) },
    { key: 'sent_at', label: 'أُرسل', type: 'date', render: r => fmtTime(r.sent_at) },
    { key: 'actions', label: '', sortable: false, render: r => (
      <div className="flex flex-wrap items-center gap-1">
        {me.can_edit && SENDABLE.includes(r.status) && cancelling !== r.id && (
          <Btn variant="danger" className="px-2 py-1" onClick={() => setCancelling(r.id)}>إلغاء</Btn>
        )}
        {me.can_edit && r.status === 'rejected' && r.purpose === 'new' && s?.gs1_offers?.[r.itemcode] && (
          <Btn className="px-2 py-1" disabled={act.pending} title={`باركود ${s.gs1_offers[r.itemcode]}`} onClick={() => gs1(r)}>جرّب GS1</Btn>
        )}
        {cancelling === r.id && <CancelRequest row={r} onClose={() => setCancelling(null)} />}
      </div>
    ) },
  ]

  return (
    <Section title="طلبات الإنتاج" data-tour="tax-invoicing-queue-production"
      hint={s ? `أصناف قرارها «يُكوَّد» جاهزة للطلب: ${fmtInt(s.ready.count)} · لدى المصلحة الآن: ${fmtInt(s.in_flight)}` : ''}
      actions={(
        <>
          {me.can_edit && (
            <Btn variant="primary" disabled={act.pending || !s?.ready.count} onClick={prepare}>
              جهّز الطلبات ({fmtInt(s?.ready.count)})
            </Btn>
          )}
          {me.can_edit && (
            <Btn disabled={act.pending || !askable.length} title={askable.length ? '' : 'لا طلبات لدى المصلحة'} onClick={refresh}>
              حدّث من المصلحة
            </Btn>
          )}
        </>
      )}>
      {state.error ? <Failed error={state.error} /> : s && (
        <div className="space-y-2 mb-2">
          {!s.enabled && <Notice tone="gray">{SWITCH_OFF}</Notice>}
          {firstRule && <Notice>{FIRST_ONLY}</Notice>}
        </div>
      )}
      {list.isLoading ? <Loading /> : list.error ? <Failed error={list.error} /> : (
        <Grid rows={rows} columns={columns} defaultSort={{ key: 'prepared_at', dir: 'desc', type: 'date' }}
          empty="لا طلبات للمنظومة الفعلية بعد" data-testid="production-requests-grid" />
      )}
      {me.can_finalize && sendable.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mt-2 text-sm">
          <span className="text-xs text-gray-600">
            {picked.length ? `المختار: ${fmtInt(chosen.length)}` : `كل الجاهز للإرسال: ${fmtInt(chosen.length)}`}
          </span>
          <input className={`${INPUT} w-24`} inputMode="numeric" aria-label="اكتب عدد الطلبات للتأكيد"
            placeholder={`اكتب ${chosen.length}`} value={typed} onChange={e => setTyped(e.target.value)} />
          <Btn variant="success" disabled={act.pending || !!sendBlock} title={sendBlock} onClick={send}>أرسل</Btn>
          {sendBlock && sendBlock !== '…' && <span role="note" className="text-xs text-amber-700">{sendBlock}</span>}
        </div>
      )}
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
      {refused.length > 0 && (
        <ul className="mt-1 text-xs text-red-700 list-disc ms-4" data-testid="production-refused">
          {refused.map(x => <li key={x.id}>{byId[x.id]?.itemcode || `#${x.id}`}: {x.why}</li>)}
        </ul>
      )}
    </Section>
  )
}
