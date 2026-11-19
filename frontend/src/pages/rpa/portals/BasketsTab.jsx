/**
 * BasketsTab — السلال: every basket (or only those that need a person), and one basket's lines with
 * their calm flags, the robot's steps and screenshots, the handed-over vs recorded diff, and the
 * settle panel (retry / link to an order, with the order's lines typed in an inline editor / cancel)
 * and, for a recorded basket that kept a reason, «acknowledge». The server refuses what is unsafe —
 * e.g. a retry while the order may have been sent, or cancelling a basket whose order was or may have
 * been placed (409: a confirmation and a reason are asked inline, never in a popup; the server says
 * up front when it will ask, cancel_needs_confirmation).
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaPortalApi } from '../../../api/client'
import useSortableRows from '../../../hooks/useSortableRows'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import {
  BASKET_STATUS, Badge, FLAG, LINE_STATUS, ModeBadge, NeedsPersonBadge, asList, credit, errText, fmtTime,
} from './shared.jsx'

const basketValue = (b, k) => (k === 'status' ? BASKET_STATUS[b.status]?.label : b[k])

const canonSku = s => String(s ?? '').replace(/\s+/g, '').replace(/^ID/i, '').replace(/^0+/, '')
const wholePacks = v => v !== '' && Number.isInteger(Number(v)) && Number(v) >= 0

// The order lines a person links: one row per basket line with a supplier code, prefilled from the
// robot's Order History read of that order (when there is one) or from the handed-over quantity.
function prefill(basket, orderRef) {
  const order = asList(basket.history_orders).find(o => o.order_ref === orderRef)
  const read = {}
  for (const r of asList(order?.lines)) {
    const k = canonSku(r.sku)
    if (k && Number.isInteger(r.qty)) read[k] = (read[k] || 0) + r.qty
  }
  const qtys = {}
  for (const ln of asList(basket.lines)) {
    if (!ln.supplier_key) continue
    const k = canonSku(ln.supplier_key)
    qtys[ln.id] = String(order ? (read[k] ?? 0) : (ln.accepted_qty ?? 0))
  }
  return qtys
}

// History rows the basket cannot account for (another code, or a row the robot could not read).
function strayRows(basket, orderRef) {
  const order = asList(basket.history_orders).find(o => o.order_ref === orderRef)
  const mine = new Set(asList(basket.lines).map(ln => canonSku(ln.supplier_key)).filter(Boolean))
  return asList(order?.lines).filter(r => !canonSku(r.sku) || !mine.has(canonSku(r.sku)) || !Number.isInteger(r.qty))
}

function LinkLinesEditor({ basket, orderRef, onSend, pending }) {
  const [qtys, setQtys] = useState(() => prefill(basket, orderRef))
  const lines = asList(basket.lines).filter(ln => ln.supplier_key)
  const stray = strayRows(basket, orderRef)
  const ok = orderRef.trim() && lines.length > 0 && lines.every(ln => wholePacks(qtys[ln.id] ?? ''))
  const send = () => onSend(lines.map(ln => ({ sku: ln.supplier_key, qty: Number(qtys[ln.id]) })))
  return (
    <div data-tour="rpa-portals-link-lines" className="rounded border border-line bg-surface p-2 space-y-2">
      <div className="text-xs text-muted">
        اكتب الكمية المطلوبة فعلاً لكل صنف كما في سجل الطلبات بالموقع (عبوات كاملة). صفر = لم يُطلب، ويرجع للباقي.
      </div>
      {asList(basket.history_orders).length > 1 && (
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <span className="text-muted">املأ من قراءة:</span>
          {basket.history_orders.map(o => (
            <button key={o.order_ref} type="button" className="btn-ghost text-xs" dir="ltr"
                    onClick={() => setQtys(prefill(basket, o.order_ref))}>{o.order_ref}{o.matched ? ' ✓' : ''}</button>
          ))}
        </div>
      )}
      <table className="w-full text-sm">
        <thead><tr className="text-muted border-b border-line">
          <th className="p-1 text-start">الصنف</th><th className="p-1 text-start">كود المورد</th>
          <th className="p-1 text-end">المُسلَّم</th><th className="p-1 text-end">في الطلب</th>
        </tr></thead>
        <tbody>
          {lines.map(ln => (
            <tr key={ln.id} className="border-b border-line">
              <td className="p-1">{ln.item_name}</td>
              <td className="p-1" dir="ltr">{ln.supplier_key}</td>
              <td className="p-1 text-end tabular-nums">{ln.accepted_qty ?? '—'}</td>
              <td className="p-1 text-end">
                <label className="sr-only" htmlFor={`pl-${ln.id}`}>الكمية في الطلب</label>
                <input id={`pl-${ln.id}`} type="number" min={0} step={1} className="input-field text-sm w-20 text-end"
                       value={qtys[ln.id] ?? ''} onChange={e => setQtys(q => ({ ...q, [ln.id]: e.target.value }))} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {stray.length > 0 && (
        <div className="text-xs text-amber-700 dark:text-amber-300">
          أسطر في سجل الطلبات لا تخص أصناف السلة (لا تُرسل):{' '}
          <span dir="ltr">{stray.map(r => `${r.sku || '?'} × ${r.qty}`).join(' · ')}</span>
          . لو أحدها صنف من السلة بكود آخر، اكتب كميته على سطر الصنف.
        </div>
      )}
      <button type="button" className="btn-primary text-sm" disabled={!ok || pending} onClick={send}>
        ربط بالطلب {orderRef.trim() && <span dir="ltr">#{orderRef.trim()}</span>} بهذه الكميات
      </button>
    </div>
  )
}

function AcknowledgePanel({ basket }) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [err, setErr] = useState('')
  const ack = useMutation({
    mutationFn: () => rpaPortalApi.resolveBasket(basket.id, { action: 'acknowledge', reason: reason.trim() }),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa-portal'] }) },
    onError: e => setErr(errText(e)),
  })
  if (basket.status !== 'recorded' || !basket.needs_person) return null
  return (
    <div data-tour="rpa-portals-acknowledge" className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2 text-sm">
      <div>مسجلة وعليها سبب يحتاج نظرة موظف: <span dir="ltr">{basket.needs_person_reason}</span></div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor={`ack-${basket.id}`}>ما راجعته</label>
        <input id={`ack-${basket.id}`} className="input-field text-sm w-72" maxLength={250} value={reason}
               onChange={e => setReason(e.target.value)} placeholder="ما راجعته (مطلوب)" />
        <button type="button" className="btn-secondary text-sm" disabled={!reason.trim() || ack.isPending}
                onClick={() => ack.mutate()}>تمت المراجعة — أزل التنبيه</button>
      </div>
      {err && <div className="text-xs text-red-600">{err}</div>}
    </div>
  )
}

function ResolvePanel({ basket }) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [orderRef, setOrderRef] = useState(basket.suggested_order_ref || basket.portal_ref || '')
  const [confirmNone, setConfirmNone] = useState(false)
  const [placedAsk, setPlacedAsk] = useState(false)
  const [placedOk, setPlacedOk] = useState(false)
  const [editLines, setEditLines] = useState(false)
  const [err, setErr] = useState('')
  const after = () => {
    setErr(''); setPlacedAsk(false); setPlacedOk(false); setEditLines(false)
    qc.invalidateQueries({ queryKey: ['rpa-portal'] })
  }
  const resolve = useMutation({
    mutationFn: data => rpaPortalApi.resolveBasket(basket.id, { reason: reason.trim(), ...data }),
    onSuccess: after,
    onError: e => {
      if (e?.response?.status === 409) setPlacedAsk(true)
      setErr(errText(e))
    },
  })
  const history = useMutation({ mutationFn: () => rpaPortalApi.historyCheck(basket.id), onSuccess: after, onError: e => setErr(errText(e)) })
  if (basket.status !== 'needs_person') return null
  const askPlaced = placedAsk || basket.cancel_needs_confirmation
  return (
    <div data-tour="rpa-portals-resolve" className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">تحتاج موظف</span>
        <span className="text-muted" dir="ltr">{basket.needs_person_reason}</span>
        <button type="button" data-tour="rpa-portals-history-refresh" className="btn-ghost text-xs ms-auto"
                disabled={history.isPending} onClick={() => history.mutate()}>
          {history.isPending ? 'جارٍ الطلب…' : '⟳ افحص سجل الطلبات الآن'}
        </button>
      </div>
      {basket.may_have_ordered && (
        <div className="text-amber-700 dark:text-amber-300 text-xs">
          ربما أُرسل الطلب (وصل الروبوت لصفحة Submit). لا تُعاد المحاولة قبل قراءة سجل الطلبات أو تأكيدك أنه لم يُرسل.
        </div>
      )}
      {String(basket.needs_person_reason || '').startsWith('history_unclear') && (
        <div className="text-amber-700 dark:text-amber-300 text-xs">
          سجل الطلبات لم يستطع التأكد أنه لا يوجد طلب لهذه السلة. راجع سجل الطلبات في الموقع، ثم اربطها بطلبها أو أكّد «لم يُرسل» واكتب السبب.
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor={`pr-reason-${basket.id}`}>السبب</label>
        <input id={`pr-reason-${basket.id}`} className="input-field text-sm w-64" maxLength={250} value={reason}
               onChange={e => setReason(e.target.value)} placeholder="سبب الحسم" />
        {basket.may_have_ordered && (
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={confirmNone} onChange={e => setConfirmNone(e.target.checked)} />
            راجعت الموقع ولم يُرسل أي طلب
          </label>
        )}
        <button type="button" className="btn-secondary text-sm" disabled={resolve.isPending}
                onClick={() => resolve.mutate({ action: 'retry', confirm_none: confirmNone })}>إعادة المحاولة</button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor={`pr-ref-${basket.id}`}>رقم الطلب</label>
        <input id={`pr-ref-${basket.id}`} className="input-field text-sm w-40" dir="ltr" maxLength={60} value={orderRef}
               onChange={e => { setOrderRef(e.target.value); setEditLines(false) }} placeholder="رقم الطلب في الموقع" />
        <button type="button" className="btn-secondary text-sm" disabled={!orderRef.trim() || resolve.isPending}
                onClick={() => resolve.mutate({ action: 'link_order', order_ref: orderRef.trim() })}>ربط بالطلب</button>
        <button type="button" className="btn-ghost text-sm" disabled={!orderRef.trim()}
                onClick={() => setEditLines(v => !v)}>{editLines ? 'إخفاء الأسطر' : 'ربط مع كتابة الأسطر'}</button>
        <button type="button" className="btn-ghost text-sm" disabled={resolve.isPending}
                onClick={() => resolve.mutate({ action: 'cancel', confirm_placed_order_cancel: placedOk })}>إلغاء السلة</button>
      </div>
      {editLines && (
        <LinkLinesEditor key={orderRef} basket={basket} orderRef={orderRef} pending={resolve.isPending}
                         onSend={lines => resolve.mutate({ action: 'link_order', order_ref: orderRef.trim(), history_lines: lines })} />
      )}
      {askPlaced && (
        <label className="flex items-center gap-1 text-xs text-red-700 dark:text-red-300">
          <input type="checkbox" checked={placedOk} onChange={e => setPlacedOk(e.target.checked)} />
          ربما طُلبت هذه السلة من الموقع: أؤكد إلغاءها (اكتب السبب أعلاه). أصنافها لن تُطلب ثانية حتى يختار لها شخص مورداً من جديد.
        </label>
      )}
      {err && <div className="text-xs text-red-600">{err}</div>}
    </div>
  )
}

function BasketDetail({ basketId }) {
  const q = useQuery({ queryKey: ['rpa-portal', 'basket', basketId], queryFn: () => rpaPortalApi.basket(basketId).then(r => r.data),
                       refetchInterval: 15000 })
  const b = q.data
  const lines = useMemo(() => asList(b?.lines), [b])
  const { sorted, headerProps } = useSortableRows(lines, { persistKey: 'portal-basket-lines',
    getValue: (r, k) => (k === 'status' ? LINE_STATUS[r.status]?.label : k === 'flags' ? (r.flags || []).length : r[k]) })
  if (q.isLoading) return <div className="card p-4 text-muted text-sm">جارٍ التحميل…</div>
  if (q.isError || !b) return <div className="card p-4 text-red-600 text-sm">تعذّر تحميل السلة.</div>
  const diff = b.diff || {}
  const diffCount = ['added', 'removed', 'qty_changed'].reduce((n, k) => n + (diff[k]?.length || 0), 0)
  return (
    <div className="card p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-bold">سلة #{b.id} (مهمة #{b.job_id} · {b.seq})</h2>
        <Badge map={BASKET_STATUS} value={b.status} />
        <NeedsPersonBadge show={b.needs_person && b.status !== 'needs_person'} />
        <ModeBadge dryRun={b.dry_run} />
        <span className="text-xs text-muted">{b.account_label}</span>
        {b.portal_ref && <span className="text-xs" dir="ltr">#{b.portal_ref}</span>}
        {b.credit_seen && Object.keys(b.credit_seen).length > 0 && <span className="text-xs text-muted">الرصيد: {credit(b.credit_seen)}</span>}
      </div>
      <AcknowledgePanel basket={b} />
      {b.status === 'awaiting_submit' && (
        <div className="text-sm rounded border border-amber-500/40 bg-amber-500/10 p-2">راجع السلة على صفحة المراجعة في الموقع ثم اضغط Submit بنفسك.</div>
      )}
      <ResolvePanel basket={b} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('item_name')} className="p-2 text-start">الصنف</SortTh>
            <SortTh {...headerProps('supplier_key')} className="p-2 text-start">كود المورد</SortTh>
            <SortTh {...headerProps('wanted_qty', 'number')} className="p-2 text-end">المطلوب</SortTh>
            <SortTh {...headerProps('accepted_qty', 'number')} className="p-2 text-end">المقبول</SortTh>
            <SortTh {...headerProps('status')} className="p-2 text-start">الحالة</SortTh>
            <SortTh {...headerProps('price', 'number')} className="p-2 text-end">السعر</SortTh>
            <SortTh {...headerProps('discount_pct', 'number')} className="p-2 text-end">الخصم %</SortTh>
            <SortTh {...headerProps('supplier_expiry', 'date')} className="p-2 text-start">الصلاحية</SortTh>
            <SortTh {...headerProps('flags', 'number')} className="p-2 text-start">علامات</SortTh>
          </tr></thead>
          <tbody>
            {sorted.map(ln => (
              <tr key={ln.id} className="border-b border-line">
                <td className="p-2">{ln.item_name} <span className="text-xs text-muted" dir="ltr">{ln.item_code}</span>
                  {ln.message && <div className="text-xs text-muted">{ln.message}</div>}</td>
                <td className="p-2" dir="ltr">{ln.supplier_key || '—'}</td>
                <td className="p-2 text-end tabular-nums">{ln.wanted_qty}</td>
                <td className="p-2 text-end tabular-nums">{ln.accepted_qty ?? '—'}</td>
                <td className="p-2"><Badge map={LINE_STATUS} value={ln.status} /></td>
                <td className="p-2 text-end tabular-nums">{ln.price ?? '—'}</td>
                <td className="p-2 text-end tabular-nums">{ln.discount_pct ?? '—'}</td>
                <td className="p-2 whitespace-nowrap">{ln.supplier_expiry || '—'}</td>
                <td className="p-2">{(ln.flags || []).map(f => <span key={f} className="me-1"><Badge map={FLAG} value={f} /></span>)}
                  {ln.bonus_text && <span className="text-xs text-muted">{ln.bonus_text}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {diffCount > 0 && (
        <div className="text-sm">
          <div className="font-semibold">الفرق بين المُسلَّم والمُسجَّل</div>
          <ul className="list-disc ms-5 text-muted" dir="ltr">
            {(diff.removed || []).map((r, i) => <li key={`r${i}`}>removed {r.sku} × {r.qty}</li>)}
            {(diff.qty_changed || []).map((r, i) => <li key={`q${i}`}>{r.sku}: {r.handed_over} → {r.recorded}</li>)}
            {(diff.added || []).map((r, i) => <li key={`a${i}`}>added {r.sku || '?'} × {String(r.qty)}</li>)}
          </ul>
        </div>
      )}
      {asList(b.runs).map(run => (
        <details key={run.id} className="rounded border border-line p-2 text-sm">
          <summary className="cursor-pointer">
            {run.kind === 'fill' ? 'تعبئة' : run.kind === 'history' ? 'سجل الطلبات' : 'أكواد'} · {fmtTime(run.started_at)} · {run.outcome || 'مفتوح'} {run.device_label && `· ${run.device_label}`}
          </summary>
          <ol className="list-decimal ms-5 mt-1 text-xs">
            {(run.steps || []).map((s, i) => (
              <li key={i} className={s.ok ? '' : 'text-red-600'}>{s.label} {s.note && <span className="text-muted">— {s.note}</span>}</li>
            ))}
          </ol>
          {(run.screenshots || []).length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {run.screenshots.map(s => (
                <a key={s.id} href={s.url} target="_blank" rel="noreferrer" className="text-xs underline">لقطة خطوة {s.step_index}</a>
              ))}
            </div>
          )}
        </details>
      ))}
    </div>
  )
}

export default function BasketsTab() {
  useHelpTab('baskets')
  const [onlyPerson, setOnlyPerson] = useState(true)
  const [basketId, setBasketId] = useState(null)
  const q = useQuery({ queryKey: ['rpa-portal', 'baskets', onlyPerson],
                       queryFn: () => rpaPortalApi.baskets(onlyPerson ? { needs_person: 1 } : {}).then(r => r.data),
                       refetchInterval: 20000 })
  const rows = useMemo(() => asList(q.data), [q.data])
  const { sorted, headerProps } = useSortableRows(rows, { getValue: basketValue, persistKey: 'portal-baskets' })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={onlyPerson} onChange={e => setOnlyPerson(e.target.checked)} /> تحتاج موظف فقط
        </label>
        <button type="button" className="btn-ghost text-xs" onClick={() => q.refetch()}>⟳ تحديث</button>
      </div>
      <div data-tour="rpa-portals-baskets" className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('id', 'number')} className="p-2 text-start">#</SortTh>
            <SortTh {...headerProps('job_id', 'number')} className="p-2 text-start">المهمة</SortTh>
            <SortTh {...headerProps('account_label')} className="p-2 text-start">الحساب</SortTh>
            <SortTh {...headerProps('status')} className="p-2 text-start">الحالة</SortTh>
            <SortTh {...headerProps('line_count', 'number')} className="p-2 text-end">الأصناف</SortTh>
            <SortTh {...headerProps('portal_ref')} className="p-2 text-start">رقم الطلب</SortTh>
            <SortTh {...headerProps('needs_person_reason')} className="p-2 text-start">السبب</SortTh>
          </tr></thead>
          <tbody>
            {sorted.map(b => (
              <tr key={b.id} onClick={() => setBasketId(b.id)}
                  className={`border-b border-line cursor-pointer hover:bg-surface-2 ${basketId === b.id ? 'bg-surface-2' : ''}`}>
                <td className="p-2 tabular-nums">{b.id}</td>
                <td className="p-2 tabular-nums">#{b.job_id} · {b.seq}</td>
                <td className="p-2">{b.account_label} <ModeBadge dryRun={b.dry_run} /></td>
                <td className="p-2"><Badge map={BASKET_STATUS} value={b.status} /> <NeedsPersonBadge show={b.needs_person && b.status !== 'needs_person'} /></td>
                <td className="p-2 text-end tabular-nums">{b.line_count}</td>
                <td className="p-2" dir="ltr">{b.portal_ref || '—'}</td>
                <td className="p-2 text-xs text-muted" dir="ltr">{b.needs_person_reason}</td>
              </tr>
            ))}
            {q.isLoading && <tr><td colSpan={7} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {q.isError && <tr><td colSpan={7} className="p-6 text-center text-red-600">تعذّر تحميل السلال.</td></tr>}
            {!q.isLoading && !q.isError && !rows.length && (
              <tr><td colSpan={7} className="p-6 text-center text-muted">{onlyPerson ? 'لا توجد سلال تحتاج موظف.' : 'لا توجد سلال.'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {basketId && <BasketDetail basketId={basketId} />}
    </div>
  )
}
