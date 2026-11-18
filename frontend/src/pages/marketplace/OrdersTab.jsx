/**
 * «📦 الطلبات» — platform orders for the user's branches (server-scoped, phones masked by the API),
 * with a side panel (not a modal) for the selected order: lines + problems + status history and the
 * accept / reject / status buttons. Accepting makes a POS draft on the platform's SOFTECH account;
 * the server decides everything (eligibility, legal moves) and answers with the refreshed order.
 */
import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { marketplaceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useServerSort from '../../hooks/useServerSort'
import useSortableRows from '../../hooks/useSortableRows'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import {
  Pager, PAY_LABEL, STATUS_LABEL, STATUS_STYLE, btnPrimary, btnQuiet, dateTime, errText, inputCls, money,
  qtyText, rowsOf, useChannels, useNotice,
} from './shared'

// The status buttons shown after acceptance. Display only: the server (apps/marketplace/intake.ALLOWED)
// refuses any move that is not allowed. Accept / reject have their own buttons.
const NEXT = {
  accepted: ['preparing', 'cancelled'],
  preparing: ['ready', 'cancelled'],
  ready: ['handed_over', 'cancelled'],
  handed_over: ['delivered'],
}
const ORDERING = ['created_at', 'status', 'channel', 'branch', 'external_id', 'platform_total', 'customer_name']

function StatusChip({ status, label }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border whitespace-nowrap ${STATUS_STYLE[status] || STATUS_STYLE.cancelled}`}>
      {label || STATUS_LABEL[status] || status}
    </span>
  )
}

function OrderPanel({ id, canCreate, onClose }) {
  const qc = useQueryClient()
  const [noticeBar, toast] = useNotice()
  const [reason, setReason] = useState('')
  const q = useQuery({ queryKey: ['marketplace', 'order', id], queryFn: () => marketplaceApi.order(id).then(r => r.data) })
  const done = (msg) => (d) => {
    qc.setQueryData(['marketplace', 'order', id], d)
    qc.invalidateQueries({ queryKey: ['marketplace', 'orders'] })
    toast.ok(msg)
  }
  const fail = (e) => {
    toast.error(errText(e))
    qc.invalidateQueries({ queryKey: ['marketplace', 'order', id] })   // accept refreshes line problems
  }
  const accept = useMutation({ mutationFn: () => marketplaceApi.accept(id).then(r => r.data), onSuccess: done('تم القبول — المسودة جاهزة في نقطة البيع'), onError: fail })
  const reject = useMutation({
    mutationFn: () => marketplaceApi.reject(id, reason).then(r => r.data),
    onSuccess: (d) => { setReason(''); done('تم الرفض')(d) }, onError: fail,
  })
  const move = useMutation({ mutationFn: (to) => marketplaceApi.setStatus(id, to).then(r => r.data), onSuccess: done('تم تحديث الحالة'), onError: fail })
  const busy = accept.isPending || reject.isPending || move.isPending
  const o = q.data
  const lines = useSortableRows(o?.lines || [], { persistKey: 'mp-order-lines' })

  return (
    <aside className="bg-white rounded-xl border p-3 space-y-3 lg:sticky lg:top-4" data-tour="marketplace-order-panel">
      <div className="flex items-center gap-2">
        <h3 className="font-bold text-gray-900">طلب {o?.external_id || '…'}</h3>
        {o && <StatusChip status={o.status} label={o.status_label} />}
        <button onClick={onClose} className="ms-auto text-gray-400 hover:text-gray-700 text-sm" aria-label="إغلاق">✕</button>
      </div>
      {q.isLoading && <div className="text-sm text-gray-400">جاري التحميل…</div>}
      {q.isError && <div className="text-sm text-red-600">{errText(q.error)}</div>}
      {o && <>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          <dt className="text-gray-500">المنصة</dt><dd>{o.channel_name}</dd>
          <dt className="text-gray-500">الفرع</dt><dd>{o.branch_name}</dd>
          <dt className="text-gray-500">العميل</dt><dd>{o.customer_name || '—'}</dd>
          <dt className="text-gray-500">الهاتف</dt><dd dir="ltr" className="text-end">{o.customer_phone || '—'}</dd>
          <dt className="text-gray-500">الدفع</dt><dd>{PAY_LABEL[o.payment_mode] || o.payment_mode}</dd>
          <dt className="text-gray-500">إجمالي المنصة</dt><dd>{money(o.platform_total)}</dd>
          {o.delivery_address && <><dt className="text-gray-500">العنوان</dt><dd>{o.delivery_address}</dd></>}
          {o.reject_reason && <><dt className="text-gray-500">سبب الرفض</dt><dd>{o.reject_reason}</dd></>}
        </dl>

        {o.pos_order && (
          <div className="rounded-lg bg-blue-50 text-blue-800 text-sm px-3 py-2">
            مسودة نقطة البيع رقم {o.pos_order.id} ({o.pos_order.status}) على حساب المنصة —{' '}
            <Link to="/pos" className="underline font-medium">افتح نقطة البيع</Link> وكمّلها من المسودات.
          </div>
        )}

        {o.problems?.length > 0 && (
          <ul className="rounded-lg bg-red-50 text-red-700 text-sm px-3 py-2 space-y-0.5">
            {o.problems.map(p => <li key={p.line}>⚠ {p.name}: {p.label}</li>)}
          </ul>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-gray-500 text-xs">
              <tr>
                <SortTh {...lines.headerProps('name')} className="text-start px-2 py-1">الصنف</SortTh>
                <SortTh {...lines.headerProps('qty', 'number')} className="text-start px-2 py-1">الكمية</SortTh>
                <SortTh {...lines.headerProps('platform_unit_price', 'number')} className="text-start px-2 py-1">سعر المنصة</SortTh>
                <SortTh {...lines.headerProps('problem_label')} className="text-start px-2 py-1">المشكلة</SortTh>
              </tr>
            </thead>
            <tbody>
              {lines.sorted.map(l => (
                <tr key={l.id} className="border-t">
                  <td className="px-2 py-1" dir="ltr">{l.name || l.external_sku}{l.item_code ? <span className="text-gray-400 text-xs"> · {l.item_code}</span> : null}</td>
                  <td className="px-2 py-1">{qtyText(l.qty)}</td>
                  <td className="px-2 py-1">{money(l.platform_unit_price)}</td>
                  <td className={`px-2 py-1 ${l.problem ? 'text-red-600' : 'text-gray-400'}`}>{l.problem ? l.problem_label : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {noticeBar}
        {canCreate && (
          <div className="space-y-2" data-tour="marketplace-order-actions">
            {o.status === 'received' && <>
              <button disabled={busy} onClick={() => accept.mutate()} className={`${btnPrimary} w-full`}>✓ قبول (مسودة في نقطة البيع)</button>
              <div className="flex gap-2">
                <input value={reason} onChange={e => setReason(e.target.value)} placeholder="سبب الرفض"
                  onKeyDown={e => { if (e.key === 'Enter' && reason.trim()) reject.mutate() }}
                  className={`${inputCls} flex-1`} />
                <button disabled={busy || !reason.trim()} onClick={() => reject.mutate()} className={btnQuiet}>رفض</button>
              </div>
            </>}
            {(NEXT[o.status] || []).length > 0 && (
              <div className="flex flex-wrap gap-2">
                {NEXT[o.status].map(to => (
                  <button key={to} disabled={busy} onClick={() => move.mutate(to)}
                    className={to === 'cancelled' ? `${btnQuiet} text-red-600` : btnQuiet}>
                    {to === 'cancelled' ? 'إلغاء الطلب' : `← ${STATUS_LABEL[to]}`}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div>
          <div className="text-xs text-gray-500 mb-1">سجل الحالات</div>
          <ol className="text-xs space-y-1">
            {(o.events || []).map(ev => (
              <li key={ev.id} className="flex gap-2">
                <span className="text-gray-400 whitespace-nowrap">{dateTime(ev.at)}</span>
                <span>{ev.from_status ? `${STATUS_LABEL[ev.from_status] || ev.from_status} ← ` : ''}{STATUS_LABEL[ev.to_status] || ev.to_status}</span>
                {ev.by_name && <span className="text-gray-500">· {ev.by_name}</span>}
                {ev.note && <span className="text-gray-500">· {ev.note}</span>}
              </li>
            ))}
          </ol>
        </div>
      </>}
    </aside>
  )
}

export default function OrdersTab({ canCreate }) {
  const channels = useChannels()
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('-created_at')
  const [openId, setOpenId] = useState(null)
  const sort = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: ORDERING, defaultOrdering: '-created_at' })
  const params = { page, ordering: ordering || undefined, status: status || undefined, channel: channel || undefined }
  const q = useQuery({
    queryKey: ['marketplace', 'orders', params],
    queryFn: () => marketplaceApi.orders(params).then(r => r.data),
    refetchInterval: 30 * 1000,
  })
  const rows = rowsOf(q.data)
  const getKey = useCallback(r => r.id, [])
  const kb = useGridKeyboard({ rows, getKey, onConfirm: r => setOpenId(r.id), onClose: () => setOpenId(null) })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <select value={status} onChange={e => { setStatus(e.target.value); setPage(1) }} className={inputCls} aria-label="الحالة">
          <option value="">كل الحالات</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={channel} onChange={e => { setChannel(e.target.value); setPage(1) }} className={inputCls} aria-label="المنصة">
          <option value="">كل المنصات</option>
          {(channels.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button onClick={() => q.refetch()} className={btnQuiet} disabled={q.isFetching}>⟳ تحديث</button>
      </div>
      <div className={`grid gap-3 ${openId ? 'lg:grid-cols-[1fr_26rem]' : ''}`}>
        <div className="bg-white rounded-xl border overflow-x-auto" {...kb.containerProps} data-tour="marketplace-orders-grid">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...sort.headerProps('created_at', 'date')} className="text-start px-3 py-2">الوقت</SortTh>
                <SortTh {...sort.headerProps('external_id')} className="text-start px-3 py-2">رقم الطلب</SortTh>
                <SortTh {...sort.headerProps('channel')} className="text-start px-3 py-2">المنصة</SortTh>
                <SortTh {...sort.headerProps('branch')} className="text-start px-3 py-2">الفرع</SortTh>
                <SortTh {...sort.headerProps('customer_name')} className="text-start px-3 py-2">العميل</SortTh>
                <SortTh {...sort.headerProps('platform_total', 'number')} className="text-start px-3 py-2">الإجمالي</SortTh>
                <SortTh {...sort.headerProps('status')} className="text-start px-3 py-2">الحالة</SortTh>
              </tr>
            </thead>
            <tbody>
              {q.isLoading && <tr><td colSpan={7} className="py-10 text-center text-gray-400">جاري التحميل…</td></tr>}
              {q.isError && <tr><td colSpan={7} className="py-10 text-center text-red-600">{errText(q.error)}</td></tr>}
              {!q.isLoading && !q.isError && rows.length === 0 && (
                <tr><td colSpan={7} className="py-10 text-center text-gray-400">لا توجد طلبات.</td></tr>
              )}
              {rows.map(r => {
                const rp = kb.rowProps(r)
                return (
                  <tr key={r.id} {...rp} onClick={() => setOpenId(r.id)}
                    className={`border-t cursor-pointer hover:bg-gray-50 ${openId === r.id ? 'bg-brand-50' : ''} ${rp.className}`}>
                    <td className="px-3 py-2 whitespace-nowrap text-gray-500">{dateTime(r.created_at)}</td>
                    <td className="px-3 py-2 font-medium" dir="ltr">{r.external_id}{r.source === 'manual' && <span className="text-[10px] text-gray-400"> · يدوي</span>}</td>
                    <td className="px-3 py-2">{r.channel_name}</td>
                    <td className="px-3 py-2">{r.branch_name}</td>
                    <td className="px-3 py-2">{r.customer_name || '—'}<div className="text-xs text-gray-400" dir="ltr">{r.customer_phone}</div></td>
                    <td className="px-3 py-2">{money(r.platform_total)}<div className="text-xs text-gray-400">{r.line_count} صنف</div></td>
                    <td className="px-3 py-2"><StatusChip status={r.status} label={r.status_label} />{r.needs_review && <span className="ms-1 text-amber-600" title="يحتاج مراجعة">⚠</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <Pager page={page} setPage={setPage} data={q.data} />
          <div className="px-3 py-1 text-[11px] text-gray-400">⌨ ↑↓ تنقل · Enter فتح الطلب · Esc إغلاق</div>
        </div>
        {openId && <OrderPanel key={openId} id={openId} canCreate={canCreate} onClose={() => setOpenId(null)} />}
      </div>
    </div>
  )
}
