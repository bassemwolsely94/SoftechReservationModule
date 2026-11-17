/**
 * StockLookupDrawer — "information at the point of need" (owner §37): for an item, show WHERE it's
 * available across the network as a visual heatmap (design-system BranchStockPill), without leaving the
 * screen, and convert the moment into fulfillment — all reusing EXISTING modules (no parallel logic):
 *   • Find-Stock  → GET /items/{id}/stock/           (read-only)
 *   • Demand (§39)→ demandApi.create  (POST /demand/)      — lost-sale capture, prefilled
 *   • Reserve(§40)→ reservationsApi.create (POST /reservations/) — platform reservation, prefilled
 *   • Transfer(§38)→ transfersApi.create (POST /transfers/)      — request from a source branch
 * All operational (no SOFTECH write). Demand/Reserve need a customer (for phone); Transfer does not.
 *
 * Used on the POS, the call centre and the omni inbox (full audit C01). `channel` tags what is created:
 *   pos → demand source walk_in · call_center → call_center / reservation order_source cc_call ·
 *   omni_whatsapp → whatsapp / cc_whatsapp · omni_call → call_center / cc_call · omni_social → online.
 * Off the POS, every branch row also offers «حجز هنا» (reserve where the stock is).
 *
 * The call centre passes onReserveAt / onTransferFrom so the record is created through the call's own
 * convert endpoints and stays linked to the call item (and the call-centre role, which may not create
 * transfers directly, uses its call-centre permission). Without them the drawer calls the APIs itself and
 * shows «تحويل» only when the user may create transfers.
 *
 * props: { item, branchId, customer, picCode, channel, fixedQty, onReserveAt, onTransferFrom,
 *          onClose, onCreated }
 *   branchId  — the customer's branch; when empty the drawer asks for it (demand / reservation / transfer
 *               target)
 *   fixedQty  — quantity is owned by the caller (call item); the quantity field is hidden
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { itemsApi, demandApi, reservationsApi, transfersApi, branchesApi } from '../api/client'
import { BranchStockPill, ActionTile, SuccessState, Icon } from '../pos/design'
import { EmptyState } from './ui'
import BranchSelect from './BranchSelect'
import { usePermission } from '../hooks/usePermission'

export const CHANNELS = {
  pos:           { demandSource: 'walk_in',     orderSource: '',            from: 'نقطة البيع' },
  call_center:   { demandSource: 'call_center', orderSource: 'cc_call',     from: 'الكول سنتر' },
  omni_whatsapp: { demandSource: 'whatsapp',    orderSource: 'cc_whatsapp', from: 'الكول سنتر — واتساب' },
  omni_call:     { demandSource: 'call_center', orderSource: 'cc_call',     from: 'الكول سنتر — مكالمة' },
  omni_social:   { demandSource: 'online',      orderSource: 'online',      from: 'الكول سنتر — سوشيال' },
}

// omni conversation's created_from_channel → drawer channel
export const omniChannel = (c) => (c === 'voice' ? 'omni_call' : c === 'whatsapp' || !c ? 'omni_whatsapp' : 'omni_social')

const errText = (e) => e?.response?.data?.detail || JSON.stringify(e?.response?.data || {}) || e?.message

export default function StockLookupDrawer({
  item, branchId, customer, picCode, channel, fixedQty,
  onReserveAt, onTransferFrom, onClose, onCreated,
}) {
  // the POS passes its own sale channel (cash / delivery / …) — anything not listed here is the POS
  const isPos = !CHANNELS[channel] || channel === 'pos'
  const ch = isPos ? CHANNELS.pos : CHANNELS[channel]
  const [rows, setRows] = useState(null)
  const [qty, setQty] = useState(1)
  const [target, setTarget] = useState(branchId ? String(branchId) : '')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)   // { kind, msg }
  const [err, setErr] = useState('')
  const mayCreateTransfer = usePermission('transfers', 'create')
  const canTransfer = Boolean(onTransferFrom) || mayCreateTransfer

  useEffect(() => { setTarget(branchId ? String(branchId) : '') }, [branchId])

  useEffect(() => {
    if (!item?.id) return
    let alive = true
    itemsApi.stock(item.id).then(({ data }) => { if (alive) setRows(data || []) })
      .catch(() => { if (alive) setRows([]) })
    return () => { alive = false }
  }, [item?.id])

  // only asked for when the caller has no branch (omni / a call without a branch)
  const { data: branches = [] } = useQuery({
    queryKey: ['branches-list'],
    queryFn:  () => branchesApi.list().then(r => r.data?.results || r.data || []),
    staleTime: 300_000,
    enabled: !branchId,
  })

  // a masked number («••••123», another branch's customer) is not a usable contact number
  const rawPhone = customer?.phone || customer?.mobileno || customer?.branchcustphone || ''
  const phone = /[•*]/.test(rawPhone) ? '' : rawPhone
  const elsewhere = (rows || []).filter(r => r.quantity_on_hand > 0 && String(r.branch) !== String(target))
  const localRow = (rows || []).find(r => String(r.branch) === String(target))
  const localQty = localRow ? localRow.quantity_on_hand : 0
  const q = fixedQty != null ? Number(fixedQty) : Math.max(1, Number(qty) || 1)
  const nameOf = (r) => r.branch_name_ar || r.branch_name

  const run = async (kind, fn, msg) => {
    setBusy(true); setErr('')
    try { const res = await fn(); setDone({ kind, msg }); onCreated?.(kind, res?.data) }
    catch (e) { setErr('تعذّر الحفظ: ' + errText(e)) }
    finally { setBusy(false) }
  }

  const needTarget = () => { if (!target) { setErr('اختر فرع العميل أولاً.'); return true } return false }

  const captureDemand = () => {
    if (!phone) return setErr('اختر عميلاً (لسحب رقم الهاتف) قبل تسجيل الطلب المفقود.')
    if (needTarget()) return
    run('demand', () => demandApi.create({
      phone, customer_name: customer?.name || '', branch: Number(target), source: ch.demandSource,
      phcode: picCode || '',
      items: [{ item: item.id, quantity: q, demand_type: 'out_of_stock' }],
    }), 'تم تسجيل الطلب المفقود — سيصل للمشتريات ويُستدعى العميل عند التوفّر.')
  }

  // reserve at `atBranch` (default: the customer's branch)
  const reserve = (atBranch = target, atName = '') => {
    if (!atBranch) return setErr('اختر فرع العميل أولاً.')
    const where = atName ? ` بفرع ${atName}` : ''
    if (onReserveAt) {
      return run('reservation', () => onReserveAt(Number(atBranch)),
        `تم إنشاء الحجز${where} وربطه بالمكالمة.`)
    }
    if (!phone) return setErr('اختر عميلاً (لسحب رقم الهاتف) قبل إنشاء الحجز.')
    run('reservation', () => reservationsApi.create({
      branch: Number(atBranch), item: item.id, quantity_requested: q,
      contact_phone: phone, contact_name: customer?.name || 'عميل',
      customer: customer?.id || null, notes: `حجز من ${ch.from}`,
      ...(ch.orderSource ? { order_source: ch.orderSource } : {}),
    }), `تم إنشاء الحجز${where} — سيُتابَع حتى توفّر الصنف وتسليمه للعميل.`)
  }

  const transfer = (sourceBranch, sourceName) => {
    if (needTarget()) return
    if (onTransferFrom) {
      return run('transfer', () => onTransferFrom(Number(sourceBranch), Number(target)),
        `تم إنشاء طلب تحويل من فرع ${sourceName} وربطه بالمكالمة.`)
    }
    run('transfer', () => transfersApi.create({
      requesting_branch: Number(target), supplying_branch: Number(sourceBranch),
      notes: `طلب تحويل من ${ch.from} — ${item?.name || ''}`,
      items: [{ item: item.id, quantity: q }],
    }), `تم إنشاء طلب تحويل من فرع ${sourceName} — يُتابَع في وحدة التحويلات.`)
  }

  const canReserve = Boolean(onReserveAt) || Boolean(phone)

  return (
    <div className="fixed inset-0 z-40 flex justify-start" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div className="relative w-[27rem] max-w-[92vw] h-full bg-surface shadow-xl border-l border-line flex flex-col"
           onClick={e => e.stopPropagation()} data-testid="stock-lookup-drawer">
        {/* header */}
        <div className="px-3 py-2 border-b border-line flex items-center gap-2">
          <Icon name="store" size={18} className="text-brand-600" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold text-content truncate">{item?.name}</div>
            <div className="text-[10px] text-faint">{item?.softech_id} · رصيد الشبكة</div>
          </div>
          <button onClick={onClose} className="text-muted hover:text-content"><Icon name="x" size={16} /></button>
        </div>

        {done ? (
          <div className="p-3"><SuccessState title="تم" detail={done.msg} /></div>
        ) : (
          <>
            <div className="flex-1 overflow-auto p-3 space-y-3">
              {/* customer's branch — only when the caller has none */}
              {!branchId && (
                <label className="block text-xs text-muted">فرع العميل
                  <BranchSelect value={target} onChange={setTarget} branches={branches} size="sm"
                                placeholder="اختر الفرع الأقرب للعميل..." className="mt-1" />
                </label>
              )}

              {/* qty */}
              {fixedQty == null ? (
                <label className="flex items-center gap-2 text-xs text-muted">الكمية
                  <input type="number" min="1" value={qty} onChange={e => setQty(e.target.value)}
                         className="w-20 border border-line rounded px-2 py-1 text-center tabnum bg-surface" />
                </label>
              ) : (
                <div className="text-xs text-muted">الكمية: <span className="tabnum text-content">{q}</span></div>
              )}

              {/* local status */}
              {target && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted">{isPos ? 'هذا الفرع:' : 'فرع العميل:'}</span>
                  <BranchStockPill name={isPos ? 'الحالى' : (localRow ? nameOf(localRow) : 'المختار')} qty={localQty} />
                </div>
              )}

              {/* network heatmap + per-branch actions */}
              {rows == null ? (
                <div className="text-xs text-faint py-6 text-center">…جارٍ قراءة رصيد الفروع</div>
              ) : elsewhere.length > 0 ? (
                <div>
                  <div className="text-[11px] font-semibold text-muted mb-1.5">
                    {target ? 'متاح بفروع أخرى' : 'متاح بالفروع'}
                  </div>
                  <div className="space-y-1">
                    {elsewhere.map(r => (
                      <div key={r.branch} className="flex items-center justify-between gap-2">
                        <BranchStockPill name={nameOf(r)} qty={r.quantity_on_hand} />
                        <div className="flex items-center gap-1">
                          {!isPos && (
                            <ActionTile icon="bookmark" label="حجز هنا" disabled={busy || !canReserve}
                                        onClick={() => reserve(r.branch, nameOf(r))}
                                        title={`حجز ${q} بفرع ${nameOf(r)} (استلام من هناك)`} />
                          )}
                          {canTransfer && (
                            <ActionTile icon="transfer" label="تحويل" disabled={busy}
                                        onClick={() => transfer(r.branch, nameOf(r))}
                                        title={`طلب تحويل ${q} من ${nameOf(r)} إلى فرع العميل`} />
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <EmptyState icon="🔴" title="لا يوجد رصيد بأى فرع"
                  sub="سجّل طلباً مفقوداً ليصل للمشتريات ويُستدعى العميل عند التوفّر." />
              )}

              {(rows || []).some(r => r.on_order_qty > 0) && (
                <div className="text-[11px] text-sky-700 flex items-center gap-1">
                  <Icon name="truck" size={12} /> يوجد كميات قيد التوريد على الشبكة
                </div>
              )}
              {!phone && <div className="text-[10px] text-amber-700">
                {onReserveAt ? 'الطلب المفقود يتطلب رقم هاتف العميل.' : 'الحجز والطلب المفقود يتطلبان اختيار عميل (لرقم الهاتف).'}
              </div>}
              {err && <div className="text-[11px] text-red-600">{err}</div>}
            </div>

            {/* actions */}
            <div className="border-t border-line p-2 flex flex-wrap items-center gap-2">
              <ActionTile icon="bookmark" label={isPos ? 'حجز للعميل' : 'حجز بفرع العميل'}
                          tone={canReserve ? 'info' : undefined}
                          onClick={() => reserve()} disabled={busy || !canReserve || !target}
                          title="إنشاء حجز على العميل بفرعه" />
              <ActionTile icon="clock" label="طلب مفقود" tone={phone ? 'promo' : undefined}
                          onClick={captureDemand} disabled={busy || !phone} title="تسجيل طلب مفقود (Demand)" />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
