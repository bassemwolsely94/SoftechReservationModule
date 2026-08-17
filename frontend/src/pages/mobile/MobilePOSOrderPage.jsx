import { useState } from 'react'
import ItemSearchInput from '../../components/ItemSearchInput'
import CustomerTypePicker from '../../components/CustomerTypePicker'
import SalespersonPicker from '../../components/SalespersonPicker'
import POSCustomerModal from '../../components/POSCustomerModal'
import { QueueIndicator } from '../POSOrderPage'
import usePosOrder, { CHANNELS, DOC_KINDS, PAY_METHODS, money, RECEIPT, CONTRACT_EMP_FIELDS } from '../../hooks/usePosOrder'

/*
 * MobilePOSOrderPage — Indirect-POS for phones. Same logic (usePosOrder) and the same
 * complete SOFTECH field set as the desktop screen, restacked for touch: config band,
 * product search, cart (expandable line details), sticky totals/actions, and slide-up
 * sheets for batches, header-extras, contract/patient data, and payment.
 */

export default function MobilePOSOrderPage() {
  const P = usePosOrder()
  const [sheet, setSheet] = useState(null)   // 'extra' | 'contract' | 'pay' | null
  const [open, setOpen] = useState(-1)       // expanded line index
  const [showCust, setShowCust] = useState(false)

  return (
    <div dir="rtl" className="pb-40 bg-gray-100 min-h-full text-sm">
      {/* config */}
      <div className="bg-white p-3 space-y-2 border-b">
        <select value={P.branch} onChange={e => P.setBranch(e.target.value)} className="w-full border rounded px-2 py-2">
          <option value="">— اختر الفرع —</option>
          {P.branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name} ({b.softech_branch_id})</option>)}
        </select>
        <div className="grid grid-cols-2 gap-2">
          <select value={P.docKind} onChange={e => P.setDocKind(e.target.value)} className="border rounded px-2 py-2">
            {DOC_KINDS.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
          <select value={P.storeCode} onChange={e => P.setStoreCode(e.target.value)} className="border rounded px-2 py-2">
            {!P.stores?.length && <option value={P.storeCode}>{P.storeCode || 'المخزن'}</option>}
            {(P.stores || []).map(s => <option key={s.storecode} value={s.storecode}>{s.storename || s.storecode}</option>)}
          </select>
        </div>
        {P.docKind === 'return' && (
          <input value={P.returnInvoice} onChange={e => P.setReturnInvoice(e.target.value)}
                 placeholder="رقم فاتورة المرتجع" className="w-full border rounded px-2 py-2" />
        )}
        {/* two-level customer: نوع العميل → إسم العميل */}
        <div className="flex gap-1 items-start">
          <div className="flex-1"><CustomerTypePicker P={P} compact /></div>
          <button onClick={() => setShowCust(true)} title="دليل العملاء الأفراد"
                  className="px-3 py-2 border rounded bg-gray-50 shrink-0 self-start mt-4">…</button>
        </div>
        {P.loyalty?.points_balance != null &&
          <div className="text-xs text-emerald-700 bg-emerald-50 rounded px-2 py-1">نقاط الولاء: {P.loyalty.points_balance}</div>}
        <button onClick={() => setSheet('extra')} className="w-full text-xs border rounded py-1.5 text-gray-600">
          بيانات الرأس (مخزن · تاريخ · خصم فكة · خيارات) ▾
        </button>
        {P.isClaim && (
          <button onClick={() => setSheet('contract')} className={`w-full text-xs rounded py-1.5 ${P.claim.patientname ? 'bg-green-50 text-green-700' : 'bg-amber-100 text-amber-800'}`}>
            بيانات التعاقد / المريض {P.claim.patientname ? '✓' : '— مطلوبة'}
          </button>
        )}
      </div>

      {/* product search + barcode + favorites */}
      <div className="p-3 bg-white border-b space-y-2">
        <ItemSearchInput onSelect={P.addItem} branchId={P.branch} />
        <input placeholder="مسح باركود ⏎" className="w-full border rounded px-2 py-2 text-sm"
               onKeyDown={e => { if (e.key === 'Enter') { P.addByBarcode(e.target.value.trim()); e.target.value = '' } }} />
        {P.favorites.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {P.favorites.map(f => <button key={f.softech_id} onClick={() => P.addItem(f)}
              className="px-2 py-1 rounded bg-amber-50 border border-amber-200 text-[11px]">⭐ {f.name?.slice(0, 16)}</button>)}
          </div>
        )}
        {Object.keys(P.suggest.map).length > 0 &&
          <button onClick={P.applyAllSuggested} className="w-full py-1.5 rounded bg-emerald-600 text-white text-xs">تطبيق الخصم المتعاقد</button>}
      </div>

      {/* cart */}
      <div className="bg-white">
        {!P.lines.length && <div className="text-center text-gray-400 py-8">لا أصناف بعد</div>}
        {P.lines.map((l, i) => {
          const net = +(l.item_sale_price * (1 - l.cust_discp / 100)) * l.qty
          return (
            <div key={i} className="border-b">
              <div className="px-3 py-2 flex justify-between items-center" onClick={() => setOpen(open === i ? -1 : i)}>
                <div>
                  <div className="font-medium">
                    <button onClick={e => { e.stopPropagation(); P.toggleFavorite(l) }} className="ml-1">{P.isFavorite(l.softech_itemcode) ? '⭐' : '☆'}</button>
                    {l.item_name}
                  </div>
                  <div className="text-xs text-gray-500">
                    {l.softech_itemcode} · {Number(l.qty)}×{money(l.item_sale_price)}
                    {' · '}{l.is_reservation ? <span className="bg-amber-100 text-amber-800 px-1 rounded">حجز</span> : (l.item_expiry || 'بدون تشغيلة')}
                    {P.suggest.map[l.softech_itemcode] != null &&
                      <button onClick={e => { e.stopPropagation(); P.applySuggested(i) }} className="text-emerald-700 mr-1">· مقترح {P.suggest.map[l.softech_itemcode]}%</button>}
                  </div>
                </div>
                <div className="text-left"><div className="font-mono">{money(net)}</div><button onClick={e => { e.stopPropagation(); P.removeLine(i) }} className="text-red-500 text-xs">حذف</button></div>
              </div>
              {open === i && (
                <div className="px-3 pb-3 grid grid-cols-3 gap-2 bg-gray-50">
                  <Fld l="الكمية"><input type="number" step="0.001" value={l.qty} onChange={e => P.setLine(i, 'qty', e.target.value)} className="minp" /></Fld>
                  <Fld l="Unit Price"><input type="number" step="0.01" value={l.item_sale_price} onChange={e => P.setLine(i, 'item_sale_price', e.target.value)} className="minp" /></Fld>
                  <Fld l="خصم %"><input type="number" step="0.01" value={l.cust_discp} onChange={e => P.setLine(i, 'cust_discp', e.target.value)} className="minp" /></Fld>
                  <Fld l="Pkg Price"><input type="number" step="0.01" value={l.pkg_price} onChange={e => P.setLine(i, 'pkg_price', e.target.value)} className="minp" /></Fld>
                  <Fld l="ض.ق %"><input type="number" step="0.01" value={l.sale_tax_pct} onChange={e => P.setLine(i, 'sale_tax_pct', e.target.value)} className="minp" /></Fld>
                  <Fld l="العبوة (بونص)"><input type="number" value={l.bonus} onChange={e => P.setLine(i, 'bonus', e.target.value)} className="minp" /></Fld>
                  <Fld l="رصيد متاح"><input value={l.available_qty ?? '—'} readOnly className="minp bg-gray-100" /></Fld>
                  <Fld l="رصيد صلاحية"><input value={l.available_expiry_qty ?? '—'} readOnly className="minp bg-gray-100" /></Fld>
                  <Fld l="رقم الباتش"><input value={l.batchno || '—'} readOnly className="minp bg-gray-100" /></Fld>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {P.fbt.length > 0 && (
        <div className="bg-white border-t p-3">
          <div className="text-xs font-semibold text-gray-600 mb-2">🛒 يُشترى معه عادةً</div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {P.fbt.map(r => (
              <button key={r.softech_id} onClick={() => P.addFbt(r)}
                      className="shrink-0 px-2 py-1.5 rounded border bg-emerald-50 border-emerald-200 text-[11px]">
                + {r.item_name?.slice(0, 18)} <span className="text-emerald-600">({Math.round(r.confidence * 100)}%)</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {P.errs.length > 0 && <ul className="text-xs bg-red-50 text-red-800 m-3 rounded p-2 list-disc pr-5 space-y-0.5">{P.errs.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {P.msg && <div className="text-xs bg-blue-50 text-blue-800 m-3 rounded p-2">{P.msg}</div>}

      {/* sticky bottom bar */}
      <div className="fixed bottom-0 inset-x-0 bg-white border-t p-3 space-y-2 z-40">
        <QueueIndicator P={P} />
        <div className="flex justify-between text-xs text-gray-600">
          <span>إجمالى {money(P.totals.gross)}</span>
          <span className="text-orange-600">خصم {money(P.totals.discount)}</span>
          <span className="font-bold text-green-700 text-base">الصافي {money(P.totals.net)}</span>
        </div>
        <div className="grid grid-cols-4 gap-2 text-xs">
          <button onClick={() => setSheet('pay')} className="py-2 rounded border">السداد ({P.tenders.length})</button>
          <button onClick={P.parkOrder} className="py-2 rounded border">⏸ تعليق</button>
          <button onClick={() => setSheet('parked')} className="py-2 rounded border">المعلّقة ({P.parked.length})</button>
          <button onClick={() => setSheet('receipt')} disabled={!P.lines.length} className="py-2 rounded border disabled:opacity-40">🧾 إيصال</button>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <button onClick={() => P.reset()} className="py-2.5 rounded border text-red-600 text-xs">أمر جديد</button>
          <button onClick={() => P.submit(false)} disabled={P.busy} className="py-2.5 rounded bg-blue-600 text-white disabled:opacity-50">{P.busy ? '...' : 'معاينة'}</button>
          {P.ref?.writer_enabled
            ? <button onClick={() => P.submit(true)} disabled={P.busy} className="py-2.5 rounded bg-red-600 text-white disabled:opacity-50">⚠ فعلي</button>
            : <button disabled className="py-2.5 rounded bg-gray-100 text-gray-400 text-xs">مُعطّل</button>}
        </div>
      </div>

      {/* parked carts */}
      {sheet === 'parked' && (
        <Sheet onClose={() => setSheet(null)} title={`السلال المعلّقة (${P.parked.length})`}>
          {!P.parked.length && <div className="text-gray-400 text-sm py-6 text-center">لا توجد سلال معلّقة</div>}
          {P.parked.map(s => (
            <div key={s.id} className="flex items-center justify-between border-b py-2 text-sm">
              <div><div className="font-medium">{s.label}</div><div className="text-xs text-gray-500">{s.lines?.length} صنف · {money(s.total)}</div></div>
              <div className="flex gap-2">
                <button onClick={() => { P.recallOrder(s.id); setSheet(null) }} className="px-3 py-1 rounded bg-blue-600 text-white text-xs">استرجاع</button>
                <button onClick={() => P.deleteParked(s.id)} className="px-2 text-red-500">✕</button>
              </div>
            </div>
          ))}
        </Sheet>
      )}

      {/* receipt preview */}
      {sheet === 'receipt' && (
        <Sheet onClose={() => setSheet(null)} title="معاينة الإيصال">
          <div className="text-center font-bold">{RECEIPT.headers[0]}</div>
          {RECEIPT.headers.slice(1).map((h, i) => (
            <div key={i} className="text-center text-[11px] text-gray-600">{h}</div>
          ))}
          <div className="text-center text-xs text-gray-500 mt-1 mb-2">إيصال بيع — {P.docDate}</div>
          <div className="text-xs mb-1">العميل: {P.customer?.name || 'Walk-In Customer'}</div>
          {P.isClaim && P.claim?.patientname && (
            <div className="text-xs mb-1">اسم المريض: {P.claim.patientname}{P.claim.patientno ? ` (${P.claim.patientno})` : ''}</div>
          )}
          <div className="text-xs mb-1">مسؤول البيع: {P.salespersonName || '—'}{P.salesperson ? ` (${P.salesperson})` : ''}</div>
          <table className="w-full text-xs border-t border-b my-2"><tbody>
            {P.lines.map((l, i) => <tr key={i}><td className="py-0.5">{l.item_name}</td><td className="text-center">{Number(l.qty)}×</td><td className="text-left">{money((l.item_sale_price * (1 - l.cust_discp / 100)) * l.qty)}</td></tr>)}
          </tbody></table>
          <div className="text-xs flex justify-between"><span>الإجمالي</span><span>{money(P.totals.gross)}</span></div>
          <div className="text-xs flex justify-between text-orange-600"><span>الخصم</span><span>{money(P.totals.discount)}</span></div>
          <div className="text-sm flex justify-between font-bold"><span>الصافي</span><span>{money(P.totals.net)}</span></div>
          {P.loyalty?.points_balance != null && <div className="text-xs text-center mt-2 text-emerald-700">نقاط الولاء: {P.loyalty.points_balance}</div>}
          <div className="border-t mt-3 pt-2 space-y-0.5">
            {RECEIPT.footers.map((f, i) => (
              <div key={i} className="text-center text-[10px] text-gray-500 leading-tight">{f}</div>
            ))}
          </div>
          <button onClick={() => window.print()} className="w-full mt-3 py-2.5 rounded bg-blue-600 text-white">🖨 طباعة</button>
        </Sheet>
      )}

      {/* batch picker */}
      {P.batchModal && (
        <Sheet onClose={() => P.setBatchModal(null)} title={`التشغيلة — ${P.batchModal.item.name}`}>
          <div className="flex items-center gap-2 mb-2 bg-gray-50 rounded p-2">
            <label className="text-xs flex-1">الكمية المطلوبة
              <input type="number" min="0" step="0.001" value={P.batchModal.need}
                     onChange={e => P.setBatchNeed(e.target.value)}
                     className="w-full border rounded px-2 py-1 mt-0.5 text-center" /></label>
            <button onClick={P.fefoFill} className="px-3 py-2 rounded bg-emerald-600 text-white text-xs shrink-0">FEFO تلقائى</button>
          </div>
          {P.batchModal.batches.map((b, i) => (
            <div key={i} className="flex items-center justify-between border-b py-2">
              <span>{b.expiry}{b.batchno ? ` (${b.batchno})` : ''}</span>
              <span className="text-xs text-gray-500">متاح {b.qty}</span>
              <input type="number" min="0" max={b.qty} step="0.001" value={P.batchModal.picks[i]}
                     onChange={e => P.setBatchModal(x => ({ ...x, picks: x.picks.map((p, j) => j === i ? e.target.value : p) }))}
                     className="w-20 border rounded px-1 text-center" />
            </div>
          ))}
          {P.batchModal.shortfall > 0 && <div className="text-xs text-amber-700 mt-1">نقص {P.batchModal.shortfall} — سيُضاف كحجز.</div>}
          <div className="text-sm font-bold mt-2">إجمالي الرصيد {P.batchModal.total}</div>
          <button onClick={P.confirmBatchPick} className="w-full mt-3 py-2.5 rounded bg-blue-600 text-white">إضافة</button>
        </Sheet>
      )}

      {/* header extras */}
      {sheet === 'extra' && (
        <Sheet onClose={() => setSheet(null)} title="بيانات الرأس">
          <M l="من حساب مخزن"><input value={P.storeCode} onChange={e => P.setStoreCode(e.target.value)} className="minp" /></M>
          <M l="مسؤول البيع (كود/اسم)"><SalespersonPicker P={P} className="minp" /></M>
          <M l="تاريخ المستند"><input type="date" value={P.docDate} onChange={e => P.setDocDate(e.target.value)} className="minp" /></M>
          <M l="أسلوب السداد"><select value={P.paymentMethod} onChange={e => P.setPaymentMethod(e.target.value)} className="minp">{PAY_METHODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}</select></M>
          <M l="خصم فكة"><input type="number" step="0.01" value={P.changeDiscount} onChange={e => P.setChangeDiscount(e.target.value)} className="minp" /></M>
          <M l="خصم العميل %"><input value={P.totals.custDiscPct} readOnly className="minp bg-gray-50" /></M>
          <M l="ما يسدده المريض">
            <input type="number" step="0.01"
                   value={P.isClaim ? P.patientPayment : P.totals.patientPays}
                   placeholder={P.totals.net} readOnly={!P.isClaim}
                   onChange={e => P.setPatientCopay(e.target.value)}
                   className={'minp' + (P.isClaim ? '' : ' bg-gray-50')} /></M>
          {P.isClaim && <M l="يتحمله التعاقد"><input value={P.totals.claimAmount} readOnly className="minp bg-amber-50" /></M>}
          <M l="ملاحظات"><input value={P.notes} onChange={e => P.setNotes(e.target.value)} className="minp" /></M>
          <div className="mt-2 space-y-1.5">
            {[['altPrice', 'السعر البديل', P.altPrice, P.setAltPrice], ['sellAtCost', 'بيع بالتكلفة', P.sellAtCost, P.setSellAtCost],
              ['printReceipt', 'طباعة رسيت', P.printReceipt, P.setPrintReceipt], ['itemsReservation', 'حجز أصناف', P.itemsReservation, P.setItemsReservation]].map(([k, lbl, v, set]) => (
              <label key={k} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v} onChange={e => set(e.target.checked)} /> {lbl}</label>
            ))}
          </div>
          <button onClick={() => setSheet(null)} className="w-full mt-3 py-2.5 rounded bg-blue-600 text-white">تم</button>
        </Sheet>
      )}

      {/* contract / patient + doctor / Rx */}
      {sheet === 'contract' && (
        <Sheet onClose={() => setSheet(null)} title="بيانات التعاقد / المريض">
          {CONTRACT_EMP_FIELDS.map(({ key, label, type }) => (
            <M key={key} l={label}><input type={type || 'text'} value={P.claim[key] || ''} onChange={e => P.setClaim({ ...P.claim, [key]: e.target.value })} className="minp" /></M>
          ))}
          <M l="تاريخ المطالبة"><input type="date" value={P.claim.claimdate || ''} onChange={e => P.setClaim({ ...P.claim, claimdate: e.target.value })} className="minp" /></M>
          <M l="الطبيب المُحيل"><input value={P.doctorName} onChange={e => P.setDoctorName(e.target.value)} className="minp" /></M>
          <M l="كود الطبيب"><input value={P.doctorCode} onChange={e => P.setDoctorCode(e.target.value)} className="minp" /></M>
          <M l="صورة الروشتة"><input type="file" accept="image/*" onChange={e => P.setRx(e.target.files?.[0] || null)} className="text-xs" /></M>
          <button onClick={() => setSheet(null)} className="w-full mt-3 py-2.5 rounded bg-blue-600 text-white">حفظ</button>
        </Sheet>
      )}

      {/* payment */}
      {sheet === 'pay' && (
        <Sheet onClose={() => setSheet(null)} title="طرق السداد">
          <div className="text-xs text-gray-500 mb-2">الصافي {money(P.totals.net)} · المدفوع {money(P.totals.paid)} · الباقي {money(P.totals.change)}</div>
          {P.tenders.map((t, i) => (
            <div key={i} className="border rounded p-2 mb-2 space-y-2">
              <div className="flex gap-2">
                <select value={t.pay_type} onChange={e => P.setTender(i, 'pay_type', e.target.value)} className="border rounded px-2 py-2">{PAY_METHODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}</select>
                <input type="number" step="0.01" value={t.amount} onChange={e => P.setTender(i, 'amount', e.target.value)} className="flex-1 border rounded px-2 py-2" placeholder="المبلغ" />
                {P.tenders.length > 1 && <button onClick={() => P.removeTender(i)} className="text-red-500 px-2">✕</button>}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <M l="العملة"><input value={t.currency} onChange={e => P.setTender(i, 'currency', e.target.value)} className="minp" /></M>
                <M l="سعر التحويل"><input type="number" step="0.0001" value={t.exchange_rate} onChange={e => P.setTender(i, 'exchange_rate', e.target.value)} className="minp" /></M>
                <M l="مسلسل داخلى"><input value={t.internal_payserial} onChange={e => P.setTender(i, 'internal_payserial', e.target.value)} className="minp" /></M>
              </div>
            </div>
          ))}
          <button onClick={P.addTender} className="text-blue-600 text-sm">+ طريقة سداد</button>
          <button onClick={() => setSheet(null)} className="w-full mt-3 py-2.5 rounded bg-blue-600 text-white">تم</button>
        </Sheet>
      )}

      {showCust && <POSCustomerModal onSelect={P.setCustomer} onClose={() => setShowCust(false)} />}

      <style>{`.minp{margin-top:.15rem;width:100%;border:1px solid #d1d5db;border-radius:.375rem;padding:.4rem .5rem;text-align:center}`}</style>
    </div>
  )
}

function Fld({ l, children }) { return <label className="text-[11px] text-gray-500 block">{l}{children}</label> }
function M({ l, children }) { return <label className="text-xs text-gray-600 block mb-2">{l}{children}</label> }
function Sheet({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end" onClick={onClose}>
      <div dir="rtl" className="bg-white w-full rounded-t-2xl p-4 max-h-[88vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-3"><span className="font-bold">{title}</span><button onClick={onClose} className="text-gray-400 text-xl">✕</button></div>
        {children}
      </div>
    </div>
  )
}
