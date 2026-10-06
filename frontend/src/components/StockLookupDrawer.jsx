/**
 * StockLookupDrawer — "information at the point of need" (owner §37): for an item, show WHERE it's
 * available across the network as a visual heatmap (design-system BranchStockPill), without leaving POS,
 * and convert the moment into fulfillment — all reusing EXISTING modules (no parallel logic):
 *   • Find-Stock  → GET /items/{id}/stock/           (read-only)
 *   • Demand (§39)→ demandApi.create  (POST /demand/)      — lost-sale capture, prefilled
 *   • Reserve(§40)→ reservationsApi.create (POST /reservations/) — platform reservation, prefilled
 *   • Transfer(§38)→ transfersApi.create (POST /transfers/)      — request from a source branch
 * All operational (no SOFTECH write). Demand/Reserve need a customer (for phone); Transfer does not.
 *
 * props: { item, branchId, customer, picCode, channel, onClose, onCreated }
 */
import { useEffect, useState } from 'react'
import { itemsApi, demandApi, reservationsApi, transfersApi } from '../api/client'
import { BranchStockPill, ActionTile, SuccessState, Icon } from '../pos/design'
import { EmptyState } from './ui'

export default function StockLookupDrawer({ item, branchId, customer, picCode, channel, onClose, onCreated }) {
  const [rows, setRows] = useState(null)
  const [qty, setQty] = useState(1)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)   // { kind, msg }
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!item?.id) return
    let alive = true
    itemsApi.stock(item.id).then(({ data }) => { if (alive) setRows(data || []) })
      .catch(() => { if (alive) setRows([]) })
    return () => { alive = false }
  }, [item?.id])

  const phone = customer?.phone || customer?.mobileno || customer?.branchcustphone
  const elsewhere = (rows || []).filter(r => r.quantity_on_hand > 0 && String(r.branch) !== String(branchId))
  const localRow = (rows || []).find(r => String(r.branch) === String(branchId))
  const localQty = localRow ? localRow.quantity_on_hand : 0
  const q = Math.max(1, Number(qty) || 1)

  const run = async (kind, fn, msg) => {
    setBusy(true); setErr('')
    try { const { data } = await fn(); setDone({ kind, msg }); onCreated?.(kind, data) }
    catch (e) { setErr('تعذّر الحفظ: ' + (e.response?.data?.detail || JSON.stringify(e.response?.data || {}) || e.message)) }
    finally { setBusy(false) }
  }

  const captureDemand = () => {
    if (!phone) return setErr('اختر عميلاً (لسحب رقم الهاتف) قبل تسجيل الطلب المفقود.')
    run('demand', () => demandApi.create({
      phone, customer_name: customer?.name || '', branch: Number(branchId), source: 'walk_in', phcode: picCode || '',
      items: [{ item: item.id, quantity: q, demand_type: 'out_of_stock' }],
    }), 'تم تسجيل الطلب المفقود — سيصل للمشتريات ويُستدعى العميل عند التوفّر.')
  }

  const reserve = () => {
    if (!phone) return setErr('اختر عميلاً (لسحب رقم الهاتف) قبل إنشاء الحجز.')
    run('reservation', () => reservationsApi.create({
      branch: Number(branchId), item: item.id, quantity_requested: q,
      contact_phone: phone, contact_name: customer?.name || 'عميل',
      customer: customer?.id || null, notes: 'حجز من نقطة البيع',
    }), 'تم إنشاء الحجز — سيُتابَع حتى توفّر الصنف وتسليمه للعميل.')
  }

  const transfer = (sourceBranch, sourceName) =>
    run('transfer', () => transfersApi.create({
      requesting_branch: Number(branchId), supplying_branch: Number(sourceBranch),
      notes: `طلب تحويل من نقطة البيع — ${item?.name || ''}`,
      items: [{ item: item.id, quantity: q }],
    }), `تم إنشاء طلب تحويل من فرع ${sourceName} — يُتابَع في وحدة التحويلات.`)

  return (
    <div className="fixed inset-0 z-40 flex justify-start" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div className="relative w-[27rem] max-w-[92vw] h-full bg-surface shadow-xl border-l border-line flex flex-col"
           onClick={e => e.stopPropagation()}>
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
              {/* qty */}
              <label className="flex items-center gap-2 text-xs text-muted">الكمية
                <input type="number" min="1" value={qty} onChange={e => setQty(e.target.value)}
                       className="w-20 border border-line rounded px-2 py-1 text-center tabnum bg-surface" />
              </label>

              {/* local status */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted">هذا الفرع:</span>
                <BranchStockPill name="الحالى" qty={localQty} />
              </div>

              {/* network heatmap + per-branch transfer */}
              {rows == null ? (
                <div className="text-xs text-faint py-6 text-center">…جارٍ قراءة رصيد الفروع</div>
              ) : elsewhere.length > 0 ? (
                <div>
                  <div className="text-[11px] font-semibold text-muted mb-1.5">متاح بفروع أخرى</div>
                  <div className="space-y-1">
                    {elsewhere.map(r => (
                      <div key={r.branch} className="flex items-center justify-between gap-2">
                        <BranchStockPill name={r.branch_name_ar || r.branch_name} qty={r.quantity_on_hand} />
                        <ActionTile icon="transfer" label="تحويل" disabled={busy}
                                    onClick={() => transfer(r.branch, r.branch_name_ar || r.branch_name)}
                                    title={`طلب تحويل ${q} من ${r.branch_name_ar || r.branch_name}`} />
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
              {!phone && <div className="text-[10px] text-amber-700">الحجز والطلب المفقود يتطلبان اختيار عميل (لرقم الهاتف).</div>}
              {err && <div className="text-[11px] text-red-600">{err}</div>}
            </div>

            {/* actions */}
            <div className="border-t border-line p-2 flex flex-wrap items-center gap-2">
              <ActionTile icon="bookmark" label="حجز للعميل" tone={phone ? 'info' : undefined}
                          onClick={reserve} disabled={busy || !phone} title="إنشاء حجز على العميل الحالى" />
              <ActionTile icon="clock" label="طلب مفقود" tone={phone ? 'promo' : undefined}
                          onClick={captureDemand} disabled={busy || !phone} title="تسجيل طلب مفقود (Demand)" />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
