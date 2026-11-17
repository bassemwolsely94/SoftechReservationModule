/**
 * «طابور الترميز» — ETA production item coding, batch S1. Items sold on production receipts with no code, biggest
 * sales first; the owner decides per item «كوّد» or «استبعد». Display only: the server pre-marks each item from where
 * it was bought, prefills the VAT rate and flags doubtful ones, applies each decision and audits it. A flagged rate is
 * chosen here (0 / 14) and the item is decided on its own; the server skips flagged items in a bulk "code".
 * Batch S2: «الفئة (GPC)» shows each item's suggested brick and where it came from; a person confirms it. The picker is
 * an inline search box; an AI suggestion that is not high-confidence is decided one item at a time.
 */
import { useEffect, useState } from 'react'
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
// where a row's brick came from (the server decides; this only labels it)
const BRICK_SOURCE = {
  decisions: 'من قرارات سابقة', eta: 'من أكواد المصلحة', sheet: 'من ملف الشركة', medicine: 'دواء', ai: 'اقتراح ذكي',
  person: 'اختيار يدوي',
}
const CONFIDENCE = { high: 'عالية', medium: 'متوسطة', low: 'منخفضة' }
const SUGGEST_MAX = 5      // each AI call can take tens of seconds (server: views.SUGGEST_MAX)
const needsBrickCheck = r => r.brick_source === 'ai' && r.brick_confidence !== 'high'
const brickLabel = b => `${b.name_ar || b.name_en || b.name || ''}`.trim()
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

function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Inline brick search (no modal): ↑↓ move, Enter picks, Esc closes. Its keys never reach the grid. */
function BrickPicker({ row, onPick, onClose, onAsk, asking }) {
  const [text, setText] = useState('')
  const [hi, setHi] = useState(0)
  const q = useDebounced(text.trim())
  const list = useQuery({ queryKey: ['tax-invoicing', 'gpc', q], queryFn: () => taxInvoicingApi.codeGpc({ q }).then(r => r.data) })
  const found = list.data?.rows || []
  const second = row.brick_second && !q ? [{ code: row.brick_second, name_ar: row.brick_second_name, second: true }] : []
  const options = [...second, ...found.filter(b => !second.some(x => x.code === b.code))]
  useEffect(() => { setHi(0) }, [q])
  const onKeyDown = e => {
    e.stopPropagation()
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi(i => Math.min(options.length - 1, i + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(i => Math.max(0, i - 1)) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      // the list may still be the one for an earlier search: wait for the results of what was typed
      if (text.trim() === q && !list.isFetching && options[hi]) onPick(options[hi])
    }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }
  return (
    <div className="mt-1 w-64 space-y-1">
      <input autoFocus className={`${INPUT} w-full`} aria-label={`بحث فئة ${row.itemcode}`} placeholder="كود أو اسم الفئة"
        value={text} onChange={e => setText(e.target.value)} onKeyDown={onKeyDown} />
      {list.data && !list.data.loaded && <div className="text-[11px] text-amber-700">قائمة GPC لم تُحمّل بعد</div>}
      <ul role="listbox" aria-label={`فئات ${row.itemcode}`} className="max-h-48 overflow-y-auto border border-gray-200 rounded-md bg-white">
        {options.map((b, i) => (
          <li key={b.code} role="option" aria-selected={i === hi}>
            <button type="button" onMouseEnter={() => setHi(i)} onClick={() => onPick(b)}
              className={`w-full text-right px-2 py-1 text-xs ${i === hi ? 'bg-primary/10' : ''}`}>
              <span dir="ltr" className="font-mono">{b.code}</span> {brickLabel(b)}
              {b.second && <span className="text-gray-400"> · بديل مقترح</span>}
            </button>
          </li>
        ))}
        {!options.length && <li className="px-2 py-1 text-xs text-gray-400">{list.isFetching ? '…' : 'لا نتائج'}</li>}
      </ul>
      <div className="flex gap-2 text-[11px]">
        {onAsk && <button type="button" className="text-primary disabled:opacity-50" disabled={asking} onClick={onAsk}>اقترح مرة أخرى</button>}
        <button type="button" className="text-gray-500" onClick={onClose}>إغلاق</button>
      </div>
    </div>
  )
}

/** The «الفئة (GPC)» cell: the brick (picked here, else the server's), where it came from, and the picker. */
function BrickCell({ row, picked, canDecide, open, onToggle, onPick, onAsk, asking }) {
  const code = picked?.code || row.brick
  const name = picked ? brickLabel(picked) : row.brick_name
  const source = picked ? 'person' : row.brick_source
  const editable = canDecide && (!row.decision || row.decision === 'code')
  const missing = row.decision === 'code' && !row.brick_confirmed
  return (
    <div className="space-y-0.5">
      {code ? (
        <div><span dir="ltr" className="font-mono text-xs">{code}</span> <span className="text-xs">{name}</span></div>
      ) : <span className="text-gray-400 text-xs">بلا فئة</span>}
      <div className="flex flex-wrap items-center gap-1">
        {source && code && (
          <Badge tone={source === 'ai' ? 'bg-violet-50 text-violet-700 border-violet-200' : undefined}>
            {BRICK_SOURCE[source] || source}{source === 'ai' && row.brick_confidence ? ` · ${CONFIDENCE[row.brick_confidence] || row.brick_confidence}` : ''}
          </Badge>
        )}
        {missing && <Badge tone="bg-red-50 text-red-700 border-red-200">تحتاج فئة</Badge>}
        {editable && (
          <button type="button" className="text-[11px] text-primary" aria-label={`اختيار فئة ${row.itemcode}`} onClick={onToggle}>
            {open ? 'إغلاق' : code ? 'تغيير' : 'اختر فئة'}
          </button>
        )}
      </div>
      {!picked && row.brick_reason && (
        <div className="text-[11px] text-gray-500 truncate max-w-[220px]" title={row.brick_reason}>{row.brick_reason}</div>
      )}
      {row.own_brick && row.own_brick !== code && (
        <div className="text-[11px] text-gray-500">في ملف الشركة: <span dir="ltr" className="font-mono">{row.own_brick}</span> {row.own_brick_name}</div>
      )}
      {open && <BrickPicker row={row} onPick={onPick} onClose={onToggle} onAsk={row.decision ? null : onAsk} asking={asking} />}
    </div>
  )
}

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
  const [bricks, setBricks] = useState({})       // itemcode → brick picked here for an undecided row
  const [picker, setPicker] = useState(null)     // itemcode whose brick picker is open
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
  // a flagged row, or one whose brick is an AI suggestion that is not high-confidence, is decided on its own.
  // `bulk`: the action started from several rows (a one-row group of a multi-row Enter is still bulk)
  const codeBlock = (list, bulk = list.length > 1) => {
    if (!list.length) return 'اختر صنفاً'
    if (bulk && list.some(r => r.vat_flagged)) return 'في المختار صنف نسبته تحتاج تأكيداً — قرره وحده'
    if (bulk && list.some(needsBrickCheck)) return 'في المختار صنف فئته اقتراح ذكي يحتاج تأكيداً — قرره وحده'
    if (bulk && list.some(r => bricks[r.itemcode])) return 'في المختار صنف اخترت فئته بنفسك — قرره وحده'
    if (list.length === 1 && list[0].vat_flagged && !rateOf(list[0])) return 'اختر نسبة الضريبة أولاً'
    if (list.length === 1 && !bricks[list[0].itemcode] && !list[0].brick) return 'اختر فئة GPC أولاً'
    return ''
  }
  const payload = (list, decision) => {
    const body = { itemcodes: list.map(r => r.itemcode), decision }
    if (decision === 'code' && list.length === 1) {
      body.vat_rate = rateOf(list[0])
      // the brick the person sees, so the server never saves a suggestion recomputed after they looked
      const brick = bricks[list[0].itemcode]?.code || list[0].brick
      if (brick) body.brick = brick
    }
    return body
  }
  const pickBrick = (r, b) => {
    setPicker(null)
    if (r.decision === 'code') {
      act.run(guard(() => taxInvoicingApi.codingSetBrick({ itemcode: r.itemcode, brick: b.code })), `سُجلت الفئة ${b.code} للصنف ${r.itemcode}`)
    } else {
      setBricks(x => ({ ...x, [r.itemcode]: b }))
    }
  }
  const askBlock = list => (!list.length ? 'اختر صنفاً' : list.length > SUGGEST_MAX ? `${SUGGEST_MAX} صنف على الأكثر في المرة` : '')
  const ask = list => {
    if (!canDecide || act.pending || askBlock(list)) return
    act.run(() => taxInvoicingApi.codingSuggest({ itemcodes: list.map(r => r.itemcode) }), d => `سُئل عن ${fmtInt(d.asked.length)}${d.skipped.length
      ? ` — تُرك ${fmtInt(d.skipped.length)}: ${d.skipped.slice(0, 3).map(s => `${s.itemcode} (${s.why})`).join('، ')}` : ''}${d.stopped === 'provider'
      ? ' — توقف السؤال: مزود الذكاء الاصطناعي لا يرد، حاول لاحقاً' : ''}`)
  }
  const summary = d => `قُرر ${fmtInt(d.decided.length)}${d.skipped.length
    ? ` — تُرك ${fmtInt(d.skipped.length)}: ${d.skipped.slice(0, 3).map(s => `${s.itemcode} (${s.why})`).join('، ')}` : ''}`
  const done = () => { setPicked([]); setNote(''); setBricks({}) }

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
    return codes.length ? codeBlock(codes, list.length > 1) : ''
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
                <Btn disabled={act.pending || !!askBlock(chosen)} title={askBlock(chosen) || 'يسأل الذكاء الاصطناعي عن فئة المختار — اقتراح فقط'}
                  onClick={() => ask(chosen)}>اقترح مرة أخرى</Btn>
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
                    <th className={TH} data-tour="tax-invoicing-queue-brick">الفئة (GPC)</th>
                    <th className={TH}>القرار</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr><td colSpan={9} className="py-8 text-center text-gray-400">✅ لا أصناف في الطابور بهذه الفلاتر</td></tr>
                  )}
                  {rows.map(r => {
                    const rp = kb.rowProps(r)
                    const pm = PREMARK[r.premark]
                    const dec = DECISION[r.decision]
                    return [
                      <tr key={r.itemcode} {...rp}
                        onClick={e => { if (!e.target.closest('button,a,input,select,textarea,label,[role=listbox]')) setOpen(o => (o === r.itemcode ? null : r.itemcode)) }}
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
                        <td className={`${TD} max-w-[260px]`}>
                          <BrickCell row={r} picked={r.decision ? null : bricks[r.itemcode]} canDecide={canDecide}
                            open={picker === r.itemcode} asking={act.pending}
                            onToggle={() => setPicker(x => (x === r.itemcode ? null : r.itemcode))}
                            onPick={b => pickBrick(r, b)} onAsk={() => ask([r])} />
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
                          <td colSpan={9} className="px-3 py-3"><Details row={r} canDecide={canDecide} /></td>
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
