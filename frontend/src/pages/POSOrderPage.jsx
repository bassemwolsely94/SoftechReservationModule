import { useState } from 'react'
import ItemSearchInput from '../components/ItemSearchInput'
import POSCustomerModal from '../components/POSCustomerModal'
import CustomerTypePicker from '../components/CustomerTypePicker'
import SalespersonPicker from '../components/SalespersonPicker'
import usePosOrder, { CHANNELS, DOC_KINDS, PAY_METHODS, money, RECEIPT, CONTRACT_EMP_FIELDS } from '../hooks/usePosOrder'

/*
 * POSOrderPage — Indirect-POS (desktop). Mirrors the SOFTECH "In-Direct Point of Sale"
 * screen field-for-field (header band, mode flags, Items / Payment / Contract-Emp-Data
 * tabs, the full item grid + batch picker), arranged like Odoo POS. Logic in usePosOrder
 * (shared with mobile). SOFTECH writes stay dry-run unless POS_WRITER_ENABLED.
 */

const NUMKEYS = ['7', '8', '9', '4', '5', '6', '1', '2', '3', '+/-', '0', '.']

export default function POSOrderPage() {
  const P = usePosOrder()
  const [showCust, setShowCust] = useState(false)
  const [showParked, setShowParked] = useState(false)
  const [showReceipt, setShowReceipt] = useState(false)
  return (
    <div dir="rtl" className="flex flex-col h-[calc(100vh-3.5rem)] bg-gray-100 text-[13px]">
      <HeaderBand P={P} onOpenCust={() => setShowCust(true)} />
      <div className="flex flex-1 overflow-hidden">
        {/* left: mode buttons + flags (SOFTECH left column) */}
        <ModeColumn P={P} />
        {/* center: tabs + grids */}
        <div className="flex-1 flex flex-col bg-white overflow-hidden">
          <Tabs P={P} />
          <div className="flex-1 overflow-auto">
            {P.activeTab === 'items' && <ItemsTab P={P} />}
            {P.activeTab === 'payment' && <PaymentTab P={P} />}
            {P.activeTab === 'contract' && <ContractTab P={P} />}
          </div>
          <FooterBar P={P} />
        </div>
        {/* right: numpad + actions (Odoo) */}
        <NumpadColumn P={P} onParked={() => setShowParked(true)} onReceipt={() => setShowReceipt(true)} />
      </div>
      {P.batchModal && <BatchModal P={P} />}
      {showCust && <POSCustomerModal onSelect={P.setCustomer} onClose={() => setShowCust(false)} />}
      {showParked && <ParkedModal P={P} onClose={() => setShowParked(false)} />}
      {showReceipt && <ReceiptModal P={P} onClose={() => setShowReceipt(false)} />}
    </div>
  )
}

function ParkedModal({ P, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div dir="rtl" className="bg-white rounded-lg p-4 w-[28rem] max-h-[80vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="font-bold mb-3">السلال المعلّقة ({P.parked.length})</div>
        {!P.parked.length && <div className="text-gray-400 text-sm py-6 text-center">لا توجد سلال معلّقة</div>}
        {P.parked.map(s => (
          <div key={s.id} className="flex items-center justify-between border-b py-2 text-sm">
            <div><div className="font-medium">{s.label}</div><div className="text-xs text-gray-500">{s.lines?.length} صنف · {money(s.total)} · {new Date(s.at).toLocaleString('ar-EG')}</div></div>
            <div className="flex gap-2">
              <button onClick={() => { P.recallOrder(s.id); onClose() }} className="px-3 py-1 rounded bg-blue-600 text-white text-xs">استرجاع</button>
              <button onClick={() => P.deleteParked(s.id)} className="px-2 text-red-500">✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ReceiptModal({ P, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 print:bg-white" onClick={onClose}>
      <div dir="rtl" id="pos-receipt" className="bg-white rounded-lg p-5 w-[22rem] max-h-[88vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="text-center font-bold">{RECEIPT.headers[0]}</div>
        {RECEIPT.headers.slice(1).map((h, i) => (
          <div key={i} className="text-center text-[11px] text-gray-600">{h}</div>
        ))}
        <div className="text-center text-xs text-gray-500 mt-1 mb-2">إيصال بيع — {P.docDate}</div>
        <div className="text-xs mb-1">العميل: {P.customer?.name || 'Walk-In Customer'}</div>
        {/* Print Employee Name of Contract Customer = ON */}
        {P.isClaim && P.claim?.patientname && (
          <div className="text-xs mb-1">اسم المريض: {P.claim.patientname}{P.claim.patientno ? ` (${P.claim.patientno})` : ''}</div>
        )}
        <div className="text-xs mb-1">مسؤول البيع: {P.salespersonName || '—'}{P.salesperson ? ` (${P.salesperson})` : ''}</div>
        <table className="w-full text-xs border-t border-b my-2">
          <tbody>
            {P.lines.map((l, i) => (
              <tr key={i}><td className="py-0.5">{l.item_name}</td><td className="text-center">{Number(l.qty)}×</td><td className="text-left">{money((l.item_sale_price * (1 - l.cust_discp / 100)) * l.qty)}</td></tr>
            ))}
          </tbody>
        </table>
        <div className="text-xs flex justify-between"><span>الإجمالي</span><span>{money(P.totals.gross)}</span></div>
        <div className="text-xs flex justify-between text-orange-600"><span>الخصم</span><span>{money(P.totals.discount)}</span></div>
        <div className="text-sm flex justify-between font-bold"><span>الصافي</span><span>{money(P.totals.net)}</span></div>
        {P.loyalty?.points_balance != null && <div className="text-xs text-center mt-2 text-emerald-700">نقاط الولاء: {P.loyalty.points_balance}</div>}
        <div className="border-t mt-3 pt-2 space-y-0.5">
          {RECEIPT.footers.map((f, i) => (
            <div key={i} className="text-center text-[10px] text-gray-500 leading-tight">{f}</div>
          ))}
        </div>
        <div className="flex gap-2 mt-4 print:hidden">
          <button onClick={onClose} className="flex-1 py-2 rounded border">إغلاق</button>
          <button onClick={() => window.print()} className="flex-1 py-2 rounded bg-blue-600 text-white">🖨 طباعة</button>
        </div>
      </div>
    </div>
  )
}

/* ───────────────────────── header band ───────────────────────── */
function HeaderBand({ P, onOpenCust }) {
  return (
    <div className="bg-white border-b px-3 py-2 grid grid-cols-4 gap-x-4 gap-y-1.5">
      <F label="مبيعات فرع">
        <select value={P.branch} onChange={e => P.setBranch(e.target.value)} className="inp">
          <option value="">—</option>
          {P.branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
        </select>
      </F>
      <F label="من حساب مخزن">
        <select value={P.storeCode} onChange={e => P.setStoreCode(e.target.value)} className="inp">
          {!P.stores?.length && <option value={P.storeCode}>{P.storeCode || '—'}</option>}
          {(P.stores || []).map(s => <option key={s.storecode} value={s.storecode}>{s.storename || s.storecode}{s.default ? ' ★' : ''}</option>)}
        </select>
      </F>
      <F label="مسؤول البيع (كود/اسم)"><SalespersonPicker P={P} className="inp" /></F>
      {P.loyalty?.points_balance != null
        ? <F label="نقاط الولاء"><input value={P.loyalty.points_balance} readOnly className="inp bg-gray-50" /></F>
        : <div />}

      {/* two-level customer: نوع العميل → إسم العميل, + … for the individual-customer directory */}
      <div className="col-span-3 flex gap-1 items-start">
        <div className="flex-1"><CustomerTypePicker P={P} /></div>
        <button onClick={onOpenCust} title="دليل العملاء الأفراد (بحث/إضافة)"
                className="px-2 py-1.5 mt-4 border rounded bg-gray-50 shrink-0 text-sm">…</button>
      </div>
      <F label="تاريخ المستند"><input type="date" value={P.docDate} onChange={e => P.setDocDate(e.target.value)} className="inp" /></F>

      <F label="نوع المستند">
        <select value={P.docKind} onChange={e => P.setDocKind(e.target.value)} className="inp">
          {DOC_KINDS.map(d => <option key={d.value} value={d.value}>{d.label} ({d.code})</option>)}
        </select>
      </F>
      <F label="أسلوب السداد">
        <select value={P.paymentMethod} onChange={e => P.setPaymentMethod(e.target.value)} className="inp">
          {PAY_METHODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </F>
      <F label="خصم فكة"><input type="number" step="0.01" value={P.changeDiscount} onChange={e => P.setChangeDiscount(e.target.value)} className="inp" /></F>
      <F label="مسلسل صرف"><input value={P.dispenseSerial} readOnly className="inp bg-gray-50" placeholder="تلقائى" /></F>
      {P.docKind === 'return'
        ? <F label="مرتجع للفاتورة #"><input value={P.returnInvoice} onChange={e => P.setReturnInvoice(e.target.value)} className="inp" /></F>
        : <F label="ملاحظات"><input value={P.notes} onChange={e => P.setNotes(e.target.value)} className="inp" /></F>}

      {/* customer-discount + patient co-pay split (as SOFTECH shows in the header) */}
      <F label="خصم العميل %"><input value={P.totals.custDiscPct} readOnly className="inp bg-gray-50" /></F>
      <F label="ما يسدده المريض">
        <input type="number" step="0.01"
               value={P.isClaim ? P.patientPayment : P.totals.patientPays}
               placeholder={P.totals.net} readOnly={!P.isClaim}
               onChange={e => P.setPatientCopay(e.target.value)}
               className={'inp' + (P.isClaim ? '' : ' bg-gray-50')} />
      </F>
      {P.isClaim && (
        <F label="يتحمله التعاقد"><input value={P.totals.claimAmount} readOnly className="inp bg-amber-50" /></F>
      )}
    </div>
  )
}

function ModeColumn({ P }) {
  const Mode = ({ ch, hot }) => (
    <button onClick={() => P.setCustType(ch.value)}
            className={`w-full text-right px-3 py-2 rounded border text-xs mb-1 ${P.custType === ch.value ? 'bg-indigo-600 text-white border-indigo-600' : 'bg-white'}`}>
      {hot && <span className="opacity-70 ml-1">{hot} =</span>} {ch.label}
    </button>
  )
  const Chk = ({ v, set, label }) => (
    <label className="flex items-center gap-1.5 text-xs mb-1.5">
      <input type="checkbox" checked={v} onChange={e => set(e.target.checked)} /> {label}
    </label>
  )
  return (
    <div className="w-44 bg-gray-50 border-l p-2 overflow-auto">
      <Mode ch={{ value: 'cash', label: 'مبيعات نقدى' }} hot="Ctrl+F2" />
      <Mode ch={{ value: 'delivery', label: 'توصيل منزلى' }} hot="Ctrl+F3" />
      <Mode ch={{ value: 'contract', label: 'مبيعات تعاقد' }} hot="Ctrl+F4" />
      <select value={P.custType} onChange={e => P.setCustType(e.target.value)} className="inp mb-3">
        {(P.custTypes || []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
      </select>
      <div className="border-t pt-2">
        <Chk v={P.altPrice} set={P.setAltPrice} label="السعر البديل" />
        <Chk v={P.sellAtCost} set={P.setSellAtCost} label="بيع بالتكلفة" />
        <Chk v={P.printReceipt} set={P.setPrintReceipt} label="طباعة رسيت" />
        <Chk v={P.itemsReservation} set={P.setItemsReservation} label="حجز أصناف (Reservation)" />
      </div>
      <div className="border-t mt-2 pt-2 text-center">
        <div className="text-[11px] text-gray-500">إجمالي المطلوب</div>
        <div className="text-2xl font-bold text-green-700">{money(P.totals.net)}</div>
      </div>
    </div>
  )
}

function Tabs({ P }) {
  const T = ({ id, label }) => (
    <button onClick={() => P.setActiveTab(id)}
            className={`px-4 py-2 text-sm border-b-2 ${P.activeTab === id ? 'border-indigo-600 text-indigo-700 font-semibold' : 'border-transparent text-gray-500'}`}>
      {label}
    </button>
  )
  return (
    <div className="flex border-b bg-gray-50">
      <T id="items" label="الأصناف [Ctrl+2]" />
      <T id="payment" label={`السداد [Ctrl+3] (${P.tenders.length})`} />
      <T id="contract" label="بيانات التعاقد [Ctrl+4]" />
    </div>
  )
}

/* ───────────────────────── Items tab ───────────────────────── */
function ItemsTab({ P }) {
  const cols = ['الباركود', 'الكود', 'الصنف', 'رصيد صلاحية متاح', 'رصيد متاح', 'ت الصلاحية',
    'رقم الباتش', 'العبوة', 'الكمية', 'Unit Price', 'Pkg Price', 'ض.ق %', 'خصم %', 'مبلغ ض.ق.م', 'سعر العبوة', 'الإجمالي', '']
  return (
    <div className="p-2">
      {/* barcode scan + favorites quick grid */}
      <div className="flex gap-2 mb-2">
        <div className="flex-1"><ItemSearchInput onSelect={P.addItem} branchId={P.branch} /></div>
        <input placeholder="مسح باركود ⏎" className="w-48 border rounded px-2 text-xs"
               onKeyDown={e => { if (e.key === 'Enter') { P.addByBarcode(e.target.value.trim()); e.target.value = '' } }} />
        {Number(P.suggest.ceiling) >= 0 && P.suggest.ceiling != null &&
          <button onClick={P.applyAllSuggested} className="px-2 rounded bg-emerald-600 text-white text-xs whitespace-nowrap">تطبيق الخصم المتعاقد</button>}
      </div>
      {P.favorites.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {P.favorites.map(f => (
            <button key={f.softech_id} onClick={() => P.addItem(f)}
                    className="px-2 py-1 rounded bg-amber-50 border border-amber-200 text-[11px]">⭐ {f.name?.slice(0, 22)}</button>
          ))}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-xs border">
          <thead className="bg-sky-700 text-white">
            <tr>{cols.map((c, i) => <th key={i} className="px-1.5 py-1 whitespace-nowrap font-medium">{c}</th>)}</tr>
          </thead>
          <tbody>
            {P.lines.map((l, i) => {
              const net = +(l.item_sale_price * (1 - l.cust_discp / 100)) * l.qty
              const taxAmt = l.sale_tax_pct ? net - net / (1 + l.sale_tax_pct / 100) : 0
              const sel = P.selected === i
              return (
                <tr key={i} onClick={() => P.setSelected(i)} className={`border-b cursor-pointer ${sel ? 'bg-indigo-50' : 'hover:bg-gray-50'}`}>
                  <Td>{l.barcode || '—'}</Td>
                  <Td>{l.softech_itemcode}</Td>
                  <Td className="text-right min-w-[180px]">
                    <button onClick={e => { e.stopPropagation(); P.toggleFavorite(l) }} title="مفضّلة"
                            className="ml-1">{P.isFavorite(l.softech_itemcode) ? '⭐' : '☆'}</button>
                    {l.item_name}{l.is_reservation && <span className="mr-1 bg-amber-100 text-amber-800 px-1 rounded">حجز</span>}
                  </Td>
                  <Td>{l.available_expiry_qty ?? '—'}</Td>
                  <Td>{l.available_qty ?? '—'}</Td>
                  <Td>{l.item_expiry || '—'}</Td>
                  <Td>{l.batchno || '—'}</Td>
                  <TdInp l={l} i={i} k="bonus" P={P} />
                  <TdInp l={l} i={i} k="qty" P={P} step="0.001" />
                  <TdInp l={l} i={i} k="item_sale_price" P={P} step="0.01" />
                  <TdInp l={l} i={i} k="pkg_price" P={P} step="0.01" />
                  <TdInp l={l} i={i} k="sale_tax_pct" P={P} step="0.01" />
                  <Td>
                    <input type="number" step="0.01" value={l.cust_discp} onClick={e => e.stopPropagation()}
                           onChange={e => P.setLine(i, 'cust_discp', e.target.value)} className="w-14 border rounded px-1 text-center" />
                    {P.suggest.map[l.softech_itemcode] != null && (
                      <button onClick={e => { e.stopPropagation(); P.applySuggested(i) }}
                              title="تطبيق الخصم المتعاقد" className="text-[10px] text-emerald-700 block w-full">مقترح {P.suggest.map[l.softech_itemcode]}%</button>
                    )}
                  </Td>
                  <Td>{money(taxAmt)}</Td>
                  <Td>{money(l.pkg_price)}</Td>
                  <Td className="font-mono">{money(net)}</Td>
                  <Td><button onClick={e => { e.stopPropagation(); P.removeLine(i) }} className="text-red-500">✕</button></Td>
                </tr>
              )
            })}
            {!P.lines.length && <tr><td colSpan={cols.length} className="text-center text-gray-400 py-8">ابحث عن صنف لإضافته (Item Search)</td></tr>}
          </tbody>
        </table>
      </div>
      {P.fbt.length > 0 && (
        <div className="mt-3 border-t pt-2">
          <div className="text-xs font-semibold text-gray-600 mb-1">🛒 يُشترى معه عادةً (Frequently Bought Together)</div>
          <div className="flex flex-wrap gap-2">
            {P.fbt.map(r => (
              <button key={r.softech_id} onClick={() => P.addFbt(r)}
                      className="px-2 py-1 rounded border bg-emerald-50 border-emerald-200 text-[11px] hover:bg-emerald-100">
                + {r.item_name?.slice(0, 26)} <span className="text-emerald-600">({Math.round(r.confidence * 100)}%)</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ───────────────────────── Payment tab ───────────────────────── */
function PaymentTab({ P }) {
  // Indirect-POS collects نقدى / آجل only. Card & cheque details are entered on the cashier
  // screen after this order is sent — not duplicated here.
  const cols = ['التاريخ', 'طريقة السداد', 'المبلغ بالعملة', 'العملة', 'سعر التحويل', 'المبلغ المحلى', 'مسلسل داخلى', '']
  return (
    <div className="p-2">
      <div className="text-xs text-gray-600 mb-2">
        الصافي <b>{money(P.totals.net)}</b> · المدفوع <b>{money(P.totals.paid)}</b> ·
        الباقي/الفكة <b className={Number(P.totals.change) < 0 ? 'text-red-600' : 'text-green-700'}>{money(P.totals.change)}</b>
      </div>
      <div className="text-[11px] text-gray-400 mb-2">تفاصيل البطاقة/الشيك تُدخل على شاشة الكاشير بعد الإرسال.</div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border">
          <thead className="bg-sky-700 text-white"><tr>{cols.map((c, i) => <th key={i} className="px-1.5 py-1 whitespace-nowrap font-medium">{c}</th>)}</tr></thead>
          <tbody>
            {P.tenders.map((t, i) => (
              <tr key={i} className="border-b">
                <Td>{P.docDate}</Td>
                <Td><select value={t.pay_type} onChange={e => P.setTender(i, 'pay_type', e.target.value)} className="inp">{PAY_METHODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}</select></Td>
                <PInp t={t} i={i} k="amount" P={P} step="0.01" />
                <Td><input value={t.currency} onChange={e => P.setTender(i, 'currency', e.target.value)} className="inp w-16" /></Td>
                <PInp t={t} i={i} k="exchange_rate" P={P} step="0.0001" />
                <Td className="font-mono">{money(Number(t.amount || 0) * Number(t.exchange_rate || 1))}</Td>
                <Td><input value={t.internal_payserial} onChange={e => P.setTender(i, 'internal_payserial', e.target.value)} className="inp w-20" /></Td>
                <Td>{P.tenders.length > 1 && <button onClick={() => P.removeTender(i)} className="text-red-500">✕</button>}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button onClick={P.addTender} className="text-blue-600 text-xs mt-2">+ طريقة سداد</button>
    </div>
  )
}

/* ─────────────────── Contract Emp. Data tab ─────────────────── */
// the 12 SOFTECH standard titles (Corp. Customer Std. Emp. Data Titles)
function ContractTab({ P }) {
  const C = (k, v) => P.setClaim({ ...P.claim, [k]: v })
  if (!P.isClaim) return <div className="p-6 text-gray-400 text-sm">تظهر بيانات المريض/المطالبة لقنوات التعاقد والتأمين فقط.</div>
  return (
    <div className="p-4">
      <div className="grid grid-cols-3 gap-3 max-w-3xl">
        {CONTRACT_EMP_FIELDS.map(({ key, label, type }) => (
          <F key={key} label={label}>
            <input type={type || 'text'} value={P.claim[key] || ''} onChange={e => C(key, e.target.value)} className="inp" />
          </F>
        ))}
        <F label="تاريخ المطالبة"><input type="date" value={P.claim.claimdate || ''} onChange={e => C('claimdate', e.target.value)} className="inp" /></F>
        <F label="الطبيب المُحيل"><input value={P.doctorName} onChange={e => P.setDoctorName(e.target.value)} className="inp" /></F>
        <F label="كود الطبيب"><input value={P.doctorCode} onChange={e => P.setDoctorCode(e.target.value)} className="inp" /></F>
        <F label="صورة الروشتة" wide><input type="file" accept="image/*" onChange={e => P.setRx(e.target.files?.[0] || null)} className="text-xs mt-1" /></F>
      </div>
    </div>
  )
}

/* ───────────────────────── footer + numpad ───────────────────────── */
function FooterBar({ P }) {
  return (
    <div className="border-t bg-gray-50 px-3 py-2 flex items-center gap-4 text-xs">
      <span>الإجمالي <b>{money(P.totals.gross)}</b></span>
      <span className="text-orange-600">الخصم <b>{money(P.totals.discount)}</b></span>
      <span>الضريبة <b>{money(P.totals.tax)}</b></span>
      <span className="text-green-700 text-base">الصافي <b>{money(P.totals.net)}</b></span>
      <div className="flex-1" />
      <span>الأصناف {P.lines.length}</span>
    </div>
  )
}

function NumpadColumn({ P, onParked, onReceipt }) {
  return (
    <div className="w-56 bg-gray-50 border-r p-2 flex flex-col gap-2 overflow-auto">
      <div className="grid grid-cols-2 gap-1">
        <button onClick={P.parkOrder} className="py-1.5 rounded bg-white border text-xs">⏸ تعليق</button>
        <button onClick={onParked} className="py-1.5 rounded bg-white border text-xs">المعلّقة ({P.parked.length})</button>
        <button onClick={onReceipt} disabled={!P.lines.length} className="py-1.5 rounded bg-white border text-xs col-span-2 disabled:opacity-40">🧾 معاينة الإيصال</button>
      </div>
      <div className="grid grid-cols-3 gap-1">
        {[['qty', 'كمية'], ['disc', 'خصم'], ['price', 'سعر']].map(([m, l]) => (
          <button key={m} onClick={() => P.setNumMode(m)} className={`py-1.5 rounded text-xs ${P.numMode === m ? 'bg-indigo-600 text-white' : 'bg-white border'}`}>{l}</button>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-1">
        {NUMKEYS.map(k => <button key={k} onClick={() => P.numpad(k)} className="py-2.5 rounded bg-white border font-semibold hover:bg-gray-100">{k}</button>)}
        <button onClick={() => P.numpad('back')} className="py-2.5 rounded bg-white border col-span-2">⌫</button>
        <button onClick={() => P.numpad('C')} className="py-2.5 rounded bg-red-50 border border-red-200 text-red-600">C</button>
      </div>
      <div className="mt-auto flex flex-col gap-1.5">
        <QueueIndicator P={P} />
        <button onClick={() => P.submit(false)} disabled={P.busy} className="py-2.5 rounded bg-blue-600 text-white disabled:opacity-50">{P.busy ? '...' : 'معاينة (تجريبي)'}</button>
        {P.ref?.writer_enabled
          ? <button onClick={() => P.submit(true)} disabled={P.busy} className="py-2.5 rounded bg-red-600 text-white disabled:opacity-50">⚠ إرسال فعلي للكاشير</button>
          : <div className="py-2 rounded bg-gray-100 text-gray-400 text-center text-[11px]">الإرسال الفعلي مُعطّل</div>}
        <button onClick={P.reset} className="py-2 rounded border text-red-600 text-xs">أمر جديد</button>
      </div>
      {P.errs.length > 0 && <ul className="text-[11px] bg-red-50 text-red-800 rounded p-1.5 list-disc pr-4">{P.errs.map((e, i) => <li key={i}>{e}</li>)}</ul>}
      {P.msg && <div className="text-[11px] bg-blue-50 text-blue-800 rounded p-1.5">{P.msg}</div>}
      <style>{`.inp{width:100%;border:1px solid #d1d5db;border-radius:.3rem;padding:.2rem .4rem;font-size:12px}`}</style>
    </div>
  )
}

export function QueueIndicator({ P }) {
  const q = P.queueStatus || {}
  const total = (q.queued || 0) + (q.push_failed || 0) + (q.pushing || 0)
  if (!total) return null
  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-1.5 text-[11px] text-amber-800">
      <div className="flex items-center justify-between">
        <span>⏳ في الطابور: <b>{q.queued || 0}</b>{q.push_failed ? ` · فشل ${q.push_failed}` : ''}{q.pushing ? ` · جارٍ ${q.pushing}` : ''}</span>
        <button onClick={P.refreshQueue} title="تحديث" className="text-amber-600">↻</button>
      </div>
      {P.ref?.writer_enabled && (q.queued || q.push_failed) > 0 && (
        <button onClick={() => P.flushNow(q.push_failed > 0)} disabled={P.busy}
                className="mt-1 w-full py-1 rounded bg-amber-600 text-white disabled:opacity-50">تفريغ الطابور الآن</button>
      )}
    </div>
  )
}

/* ───────────────────────── shared bits ───────────────────────── */
function F({ label, children, wide }) {
  return <label className={`text-[11px] text-gray-600 block ${wide ? 'col-span-2' : ''}`}>{label}{children}</label>
}
function Td({ children, className = '' }) { return <td className={`px-1.5 py-1 text-center whitespace-nowrap ${className}`}>{children}</td> }
function TdInp({ l, i, k, P, step = '1' }) {
  return <Td><input type="number" step={step} value={l[k]} onClick={e => e.stopPropagation()} onChange={e => P.setLine(i, k, e.target.value)} className="w-16 border rounded px-1 text-center" /></Td>
}
function PInp({ t, i, k, P, step }) {
  return <Td><input type="number" step={step} value={t[k]} onChange={e => P.setTender(i, k, e.target.value)} className="w-24 border rounded px-1 text-center" /></Td>
}

function BatchModal({ P }) {
  const m = P.batchModal
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => P.setBatchModal(null)}>
      <div dir="rtl" className="bg-white rounded-lg p-4 w-[36rem] max-h-[85vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="font-bold mb-1">Item Code: {m.item.softech_id} — WareHouse: {P.storeCode || '—'}</div>
        <div className="text-xs text-gray-500 mb-3">{m.item.name} — اختر من تشغيلة أو وزّع على أكثر من صلاحية.</div>
        <table className="w-full text-sm">
          <thead className="bg-sky-700 text-white"><tr><th className="py-1 px-2">رقم تشغيلة</th><th>الكمية المتاحة</th><th>إنتهاء الصلاحية</th><th>المطلوب</th></tr></thead>
          <tbody>
            {m.batches.map((b, i) => (
              <tr key={i} className="border-b text-center">
                <td className="py-1">{b.batchno || '—'}</td><td>{b.qty}</td><td>{b.expiry}</td>
                <td><input type="number" min="0" max={b.qty} step="0.001" value={m.picks[i]}
                       onChange={e => P.setBatchModal(x => ({ ...x, picks: x.picks.map((p, j) => j === i ? e.target.value : p) }))}
                       className="w-20 border rounded px-1 text-center" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="flex items-center justify-between mt-3 bg-gray-50 rounded p-2">
          <div className="text-sm font-bold">إجمالي الرصيد {m.total}</div>
          <div className="flex items-center gap-2">
            <label className="text-xs">الكمية المطلوبة
              <input type="number" min="0" step="0.001" value={m.need}
                     onChange={e => P.setBatchNeed(e.target.value)}
                     className="w-20 border rounded px-1 text-center mr-1" /></label>
            <button onClick={P.fefoFill} title="تعبئة تلقائية من الأقرب انتهاءً"
                    className="px-3 py-1.5 rounded bg-emerald-600 text-white text-xs">FEFO تعبئة تلقائية</button>
          </div>
        </div>
        {m.shortfall > 0 && <div className="text-xs text-amber-700 mt-1">نقص {m.shortfall} — سيُضاف كحجز عند الإضافة.</div>}
        <div className="flex justify-end gap-2 mt-3">
          <button onClick={() => P.setBatchModal(null)} className="px-4 py-1.5 rounded border">إلغاء (Esc)</button>
          <button onClick={P.confirmBatchPick} className="px-4 py-1.5 rounded bg-blue-600 text-white">إضافة</button>
        </div>
      </div>
    </div>
  )
}
