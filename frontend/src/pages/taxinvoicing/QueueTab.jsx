/**
 * «طابور الترميز» — ETA production item coding, batch S1. Items sold on production receipts with no code, biggest
 * sales first; the owner decides per item «كوّد» or «استبعد». Display only: the server pre-marks each item from where
 * it was bought, prefills the VAT rate and flags doubtful ones, applies each decision and audits it. A flagged rate is
 * chosen here (0 / 14) and the item is decided on its own; the server skips flagged items in a bulk "code".
 */
import { useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useServerSort from '../../hooks/useServerSort'
import { ActionMsg, Badge, Btn, errText, Failed, fmt, fmtDate, fmtInt, fmtTime, Grid, INPUT, Loading, Section, useAction } from './ui'

const SORT = ['value', 'docs', 'last_day', 'itemcode', 'premark']
const TH = 'px-2 py-2 font-semibold whitespace-nowrap text-right'
const TD = 'px-2 py-2 align-top'

const PREMARK = {
  code: { label: 'كوّد', tone: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  keep_out: { label: 'استبعد', tone: 'bg-gray-100 text-gray-700 border-gray-300' },
}
const DECISION = {
  code: { label: '✅ يُكوَّد', tone: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  keep_out: { label: '⛔ خارج الترميز', tone: 'bg-gray-100 text-gray-700 border-gray-300' },
}
const SOURCE = {
  OFFICIAL_DISTRIBUTOR: 'موزع رسمي', DRUG_WAREHOUSE: 'مخزن أدوية', MANUFACTURER: 'مصنع', SMALL_WAREHOUSE: 'مستودع صغير',
  UNKNOWN: 'غير مصنف',
}
const VAT_WHY = {
  confirmed: 'معاملة اعتمدها المحاسب', catalog: 'من نسبة الصنف في SOFTECH', no_catalog: 'الصنف ليس في الكتالوج — اختر النسبة',
  odd_rate: 'نسبة غير 0 أو 14 — اختر النسبة', zero_for_type: 'صفر لنوع يُتوقع أن يخضع — تأكد',
  taxed_medicine: 'دواء بنسبة 14 — تأكد',
}
const KEYS_HINT = '⌨ ↑↓ تنقل · مسافة تحديد · Enter قبول المقترح · C كوّد · K استبعد · M التفاصيل · Ctrl+A تحديد الكل'

const sourcesText = s => Object.entries(s || {}).sort((a, b) => b[1] - a[1])
  .map(([k, q]) => `${SOURCE[k] || k} ${fmtInt(Math.round(q))}`).join(' · ') || 'لا مشتريات'
const QUEUE_KEY = ['tax-invoicing', 'coding-queue']
// useAction reloads only on success; a refused decision (409, a rule) may still mean the list moved, so reload then too
function useReloadOnError() {
  const qc = useQueryClient()
  return call => async () => {
    try { return await call() } catch (e) { qc.invalidateQueries({ queryKey: QUEUE_KEY }); throw e }
  }
}
// keys a focused button or link inside the grid owns (it clicks on Enter / Space)
const BUTTON_KEYS = new Set(['Enter', 'NumpadEnter', 'Space', 'KeyC', 'KeyK', 'KeyM'])
const isTyping = t => t && (t.isContentEditable || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA'
  || (t.tagName === 'INPUT' && !['checkbox', 'radio', 'button'].includes(t.type)))

function Reopen({ row, onDone }) {
  const [reason, setReason] = useState('')
  const act = useAction()
  const guard = useReloadOnError()
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input className={`${INPUT} w-64`} aria-label={`سبب إعادة فتح ${row.itemcode}`} placeholder="سبب إعادة الفتح"
        value={reason} onChange={e => setReason(e.target.value)} />
      <Btn variant="danger" disabled={act.pending || !reason.trim()}
        onClick={() => act.run(guard(() => taxInvoicingApi.codingReopen({ itemcode: row.itemcode, reason })), 'أُعيد فتح الصنف', onDone)}>
        إعادة فتح
      </Btn>
      <ActionMsg msg={act.msg} />
    </div>
  )
}

function Details({ row, canDecide }) {
  return (
    <div className="space-y-2 text-xs text-gray-600">
      <div>المصادر: {sourcesText(row.sources)}</div>
      <div>الضريبة: {fmt(row.vat_rate, 0)}% — {VAT_WHY[row.vat_why] || row.vat_why || '—'}</div>
      {row.eta_last_status && <div>آخر حالة لدى المصلحة: {row.eta_last_status}</div>}
      {row.decision && (
        <div>القرار: {DECISION[row.decision]?.label || row.decision} · {row.decided_by || '—'} · {fmtTime(row.decided_at)}</div>
      )}
      {row.decision && canDecide && <Reopen row={row} />}
    </div>
  )
}

/** What ETA production already holds for us against the coding sheet. Reads only. */
export function EtaHolds() {
  const [open, setOpen] = useState(false)
  const q = useQuery({ queryKey: ['tax-invoicing', 'eta-holds', 'production'],
    queryFn: () => taxInvoicingApi.etaHolds({ system: 'production' }).then(r => r.data) })
  const c = q.data?.counts || {}
  return (
    <Section title="ما لدى المصلحة" data-tour="tax-invoicing-queue-eta-holds"
      hint={q.data
        ? `في المنظومة الفعلية: ${fmtInt(c.usages)} سجل · مفعّل ${fmtInt(c.active)} · مربوط بصنف في ملفنا ${fmtInt(c.matched)} · غير مربوط ${fmtInt(c.unmatched)} · في ملف الأكواد ${fmtInt(c.sheet)} · في الملف وليس لدى المصلحة ${fmtInt(q.data.in_sheet_not_on_eta.length)}`
        : 'أكواد مفعلة لدى المصلحة الفعلية مقابل ملف الأكواد. قراءة فقط.'}
      actions={<Btn onClick={() => setOpen(x => !x)}>{open ? 'إخفاء' : 'عرض'} ما لدى المصلحة وليس في الملف ({fmtInt(q.data?.on_eta_not_in_sheet?.length)})</Btn>}>
      {q.isLoading ? <Loading /> : q.error ? <Failed error={q.error} /> : open && (
        <Grid rows={q.data.on_eta_not_in_sheet} getKey={r => `${r.code_type}|${r.item_code}`}
          empty="✅ كل ما لدى المصلحة موجود في ملف الأكواد" columns={[
            { key: 'code_type', label: 'النوع' },
            { key: 'item_code', label: 'كود المصلحة', render: r => <span dir="ltr" className="font-mono text-xs">{r.item_code}</span> },
            { key: 'code_name', label: 'الاسم لدى المصلحة', className: 'max-w-[260px] truncate' },
            { key: 'itemcode', label: 'صنف SOFTECH', render: r => r.itemcode || 'غير مربوط' },
            { key: 'status', label: 'الحالة' },
          ]} />
      )}
    </Section>
  )
}

export default function QueueTab({ me }) {
  const canDecide = !!me.can_approve
  const act = useAction()
  const guard = useReloadOnError()
  const [page, setPageRaw] = useState(1)
  const [ordering, setOrdering] = useState('-value')
  const [f, setF] = useState({ premark: '', decided: 'no', recent: false, q: '' })
  const [picked, setPicked] = useState([])
  // a new page, sort or filter shows other rows: the ticks go with the old ones
  const setPage = v => { setPageRaw(v); setPicked([]) }
  const [rates, setRates] = useState({})
  const [open, setOpen] = useState(null)
  const [note, setNote] = useState('')
  const { headerProps } = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: SORT, defaultOrdering: '-value' })
  const params = { page, ordering, ...(f.premark ? { premark: f.premark } : {}), ...(f.decided ? { decided: f.decided } : {}),
    ...(f.recent ? { recent: 90 } : {}), ...(f.q.trim() ? { q: f.q.trim() } : {}) }
  const q = useQuery({ queryKey: ['tax-invoicing', 'coding-queue', params],
    queryFn: () => taxInvoicingApi.codingQueue(params).then(r => r.data), placeholderData: keepPreviousData })
  const rows = q.data?.rows || []
  const set = (k, v) => { setF(x => ({ ...x, [k]: v })); setPage(1) }

  const toggle = r => { if (canDecide && !r.decision) setPicked(p => (p.includes(r.itemcode) ? p.filter(x => x !== r.itemcode) : [...p, r.itemcode])) }
  const selection = row => (picked.length ? rows.filter(r => picked.includes(r.itemcode)) : row ? [row] : []).filter(r => !r.decision)
  const chosen = selection(null)
  const rateOf = r => (r.vat_flagged ? rates[r.itemcode] : r.vat_rate)
  // a flagged row is decided on its own, with the rate chosen for it
  const codeBlock = list => {
    if (!list.length) return 'اختر صنفاً'
    if (list.length > 1 && list.some(r => r.vat_flagged)) return 'في المختار صنف نسبته تحتاج تأكيداً — قرره وحده'
    if (list.length === 1 && list[0].vat_flagged && !rateOf(list[0])) return 'اختر نسبة الضريبة أولاً'
    return ''
  }
  const payload = (list, decision) => {
    const body = { itemcodes: list.map(r => r.itemcode), decision }
    if (decision === 'code' && list.length === 1) body.vat_rate = rateOf(list[0])
    return body
  }
  const summary = d => `قُرر ${fmtInt(d.decided.length)}${d.skipped.length
    ? ` — تُرك ${fmtInt(d.skipped.length)}: ${d.skipped.slice(0, 3).map(s => `${s.itemcode} (${s.why})`).join('، ')}` : ''}`
  const done = () => { setPicked([]); setNote('') }

  const decide = (decision, list) => {
    if (!canDecide || act.pending) return
    const why = decision === 'code' ? codeBlock(list) : list.length ? '' : 'اختر صنفاً'
    if (why) { setNote(why); return }
    setNote('')
    act.run(guard(() => taxInvoicingApi.codingDecide(payload(list, decision))), summary, done)
  }
  // Enter: each row takes its own pre-mark; rows with no pre-mark are left
  const acceptBlock = list => {
    const marked = list.filter(r => r.premark)
    if (!marked.length) return 'لا مقترح في المختار'
    const codes = marked.filter(r => r.premark === 'code')
    if (list.length > 1 && list.some(r => r.vat_flagged)) return codeBlock(list)
    return codes.length ? codeBlock(codes) : ''
  }
  const accept = list => {
    if (!canDecide || act.pending) return
    const why = acceptBlock(list)
    if (why) { setNote(why); return }
    setNote('')
    const groups = ['code', 'keep_out'].map(d => [d, list.filter(r => r.premark === d)]).filter(([, l]) => l.length)
    const left = list.filter(r => !r.premark).map(r => ({ itemcode: r.itemcode, why: 'بلا مقترح' }))
    act.run(async () => {
      const out = { decided: [], skipped: [...left] }
      // each group on its own: one refused group is reported and the other still saved
      for (const [d, l] of groups) {
        try {
          const { data } = await taxInvoicingApi.codingDecide(payload(l, d))
          out.decided.push(...data.decided)
          out.skipped.push(...data.skipped)
        } catch (e) {
          out.skipped.push(...l.map(r => ({ itemcode: r.itemcode, why: errText(e) })))
        }
      }
      return { data: out }
    }, summary, done)
  }

  const kb = useGridKeyboard({
    rows, getKey: r => r.itemcode, enabled: !!rows.length,
    onToggle: toggle,
    onConfirm: r => accept(selection(r)),
    onOpen: r => setOpen(o => (o === r.itemcode ? null : r.itemcode)),
    onSelectAll: () => canDecide && setPicked(rows.filter(r => !r.decision).map(r => r.itemcode)),
  })
  const activeRow = rows.find(r => r.itemcode === kb.active) || null
  // C / K act before the shared hook, which reads K as "up"
  const onKeyDown = e => {
    if (BUTTON_KEYS.has(e.code) && e.target !== e.currentTarget && e.target.closest?.('button, a')) return
    if (!isTyping(e.target) && !e.ctrlKey && !e.metaKey && !e.altKey && (e.code === 'KeyC' || e.code === 'KeyK')) {
      e.preventDefault()
      e.stopPropagation()
      decide(e.code === 'KeyC' ? 'code' : 'keep_out', selection(activeRow))
      return
    }
    kb.containerProps.onKeyDown(e)
  }

  const d = q.data
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        أصناف بيعت على إيصالات المنظومة الفعلية بلا كود، مرتبة بقيمة المبيعات. المقترح من مصادر الشراء والنسبة من SOFTECH
        مدخلات فقط؛ قرارك هو ما يُحفظ ويُسجّل. الصنف الذي نسبته تحتاج تأكيداً يُقرر وحده بعد اختيار النسبة.
      </p>
      <Section title="طابور الترميز"
        hint={d ? `${fmtInt(d.count)} صنف · مبيعات بلا كود ${fmt(d.total_value)} ج` : ''}
        actions={(
          <>
            {d?.catalog_without_profile && me.can_edit && (
              <Btn disabled={act.pending}
                onClick={() => act.run(() => taxInvoicingApi.codesAddFromCatalog(), r => `أُضيف ${fmtInt(r.added)} صنف من الكتالوج`)}>
                إضافة أصناف الكتالوج الجديدة
              </Btn>
            )}
            {canDecide && (
              <>
                <Btn variant="primary" disabled={act.pending || !!acceptBlock(chosen)} title={acceptBlock(chosen)}
                  onClick={() => accept(chosen)}>قبول المقترح ({fmtInt(chosen.length)})</Btn>
                <Btn variant="success" disabled={act.pending || !!codeBlock(chosen)} title={codeBlock(chosen)}
                  onClick={() => decide('code', chosen)}>كوّد</Btn>
                <Btn disabled={act.pending || !chosen.length} onClick={() => decide('keep_out', chosen)}>استبعد</Btn>
              </>
            )}
          </>
        )}>
        <div className="flex flex-wrap items-center gap-2 mb-2 text-sm">
          <input className={`${INPUT} w-56`} aria-label="بحث" placeholder="بحث بالكود أو الاسم" value={f.q} onChange={e => set('q', e.target.value)} />
          <select className={INPUT} aria-label="المقترح" value={f.premark} onChange={e => set('premark', e.target.value)}>
            <option value="">كل المقترحات</option>
            <option value="code">مقترح: كوّد</option>
            <option value="keep_out">مقترح: استبعد</option>
            <option value="none">بلا مقترح</option>
          </select>
          <select className={INPUT} aria-label="القرار" value={f.decided} onChange={e => set('decided', e.target.value)}>
            <option value="no">بلا قرار</option>
            <option value="yes">له قرار</option>
            <option value="">الكل</option>
          </select>
          <label className="flex items-center gap-1 text-xs text-gray-600">
            <input type="checkbox" checked={f.recent} onChange={e => set('recent', e.target.checked)} />
            آخر 90 يوماً
          </label>
        </div>
        {q.isLoading ? <Loading /> : q.error ? <Failed error={q.error} /> : (
          <>
            <div {...kb.containerProps} onKeyDown={onKeyDown} data-testid="coding-queue-grid" data-tour="tax-invoicing-queue-grid"
              className={`bg-white rounded-xl border border-gray-200 overflow-x-auto ${kb.containerProps.className}`}>
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
                    {canDecide && <th className={TH} aria-label="تحديد" />}
                    <SortTh {...headerProps('itemcode')} className={TH}>الصنف</SortTh>
                    <SortTh {...headerProps('value', 'number')} className={TH}>المبيعات بلا كود</SortTh>
                    <SortTh {...headerProps('last_day', 'date')} className={TH}>آخر بيع</SortTh>
                    <th className={TH}>المصدر</th>
                    <SortTh {...headerProps('premark')} className={TH}>المقترح</SortTh>
                    <th className={TH}>الضريبة</th>
                    <th className={TH}>القرار</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr><td colSpan={8} className="py-8 text-center text-gray-400">✅ لا أصناف في الطابور بهذه الفلاتر</td></tr>
                  )}
                  {rows.map(r => {
                    const rp = kb.rowProps(r)
                    const pm = PREMARK[r.premark]
                    const dec = DECISION[r.decision]
                    return [
                      <tr key={r.itemcode} {...rp}
                        onClick={e => { if (!e.target.closest('button,a,input,select,textarea,label')) setOpen(o => (o === r.itemcode ? null : r.itemcode)) }}
                        className={`border-b border-gray-100 cursor-pointer hover:bg-gray-50 ${picked.includes(r.itemcode) ? 'bg-primary/5' : ''} ${rp.className}`}>
                        {canDecide && (
                          <td className={TD}>
                            {!r.decision && <input type="checkbox" checked={picked.includes(r.itemcode)} onChange={() => toggle(r)} aria-label={`اختيار ${r.itemcode}`} />}
                          </td>
                        )}
                        <td className={`${TD} max-w-[260px]`}>
                          <div className="truncate">{r.name || r.name_ar || '—'}</div>
                          <div className="text-[11px] text-gray-400">{r.itemcode}</div>
                        </td>
                        <td className={TD}>
                          <div className="font-semibold">{fmt(r.value)}</div>
                          <div className="text-[11px] text-gray-400">{fmtInt(r.docs)} إيصال</div>
                        </td>
                        <td className={`${TD} whitespace-nowrap`}>{fmtDate(r.last_day)}</td>
                        <td className={`${TD} text-xs text-gray-600 max-w-[200px]`}>{sourcesText(r.sources)}</td>
                        <td className={`${TD} max-w-[240px]`}>
                          {pm ? <Badge tone={pm.tone}>{pm.label}</Badge> : <span className="text-gray-400 text-xs">بلا مقترح</span>}
                          {r.note && <div className="text-[11px] text-gray-500 mt-0.5">{r.note}</div>}
                        </td>
                        <td className={`${TD} whitespace-nowrap`}>
                          {r.vat_flagged && !r.decision && canDecide ? (
                            <select className={`${INPUT} border-red-300 text-red-700`} aria-label={`نسبة ضريبة ${r.itemcode}`}
                              title={VAT_WHY[r.vat_why] || ''} value={rates[r.itemcode] || ''}
                              onChange={e => setRates(x => ({ ...x, [r.itemcode]: e.target.value }))}>
                              <option value="">اختر ({fmt(r.vat_rate, 0)}%؟)</option>
                              <option value="0">0%</option>
                              <option value="14">14%</option>
                            </select>
                          ) : (
                            <span className={r.vat_flagged ? 'text-red-700 font-semibold' : ''} title={VAT_WHY[r.vat_why] || ''}>
                              {fmt(r.vat_rate, 0)}%
                            </span>
                          )}
                        </td>
                        <td className={`${TD} whitespace-nowrap`}>
                          {dec ? (
                            <>
                              <Badge tone={dec.tone}>{dec.label}</Badge>
                              <div className="text-[11px] text-gray-400">{r.decided_by}</div>
                            </>
                          ) : canDecide ? (
                            <div className="flex gap-1">
                              <Btn variant="success" className="px-2 py-1" disabled={act.pending || !!codeBlock([r])} title={codeBlock([r])}
                                onClick={() => decide('code', [r])}>كوّد</Btn>
                              <Btn className="px-2 py-1" disabled={act.pending} onClick={() => decide('keep_out', [r])}>استبعد</Btn>
                            </div>
                          ) : '—'}
                        </td>
                      </tr>,
                      open === r.itemcode && (
                        <tr key={`${r.itemcode}-open`} className="bg-gray-50/60 border-b border-gray-100">
                          <td colSpan={8} className="px-3 py-3"><Details row={r} canDecide={canDecide} /></td>
                        </tr>
                      ),
                    ]
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs mt-2">
              <Btn disabled={page <= 1} onClick={() => setPage(p => p - 1)}>السابق</Btn>
              <span>صفحة {fmtInt(d.page)} من {fmtInt(d.pages)}</span>
              <Btn disabled={page >= d.pages} onClick={() => setPage(p => p + 1)}>التالي</Btn>
              {canDecide && <span className="text-gray-400 ms-auto">{KEYS_HINT}</span>}
            </div>
          </>
        )}
        {note && <div role="status" className="text-xs text-amber-700 mt-2">{note}</div>}
        <div className="mt-2"><ActionMsg msg={act.msg} /></div>
      </Section>
      <EtaHolds />
    </div>
  )
}
