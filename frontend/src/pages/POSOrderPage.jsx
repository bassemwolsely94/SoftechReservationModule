import { useState, useEffect, useRef, useMemo } from 'react'
import usePosHotkeys from '../hooks/usePosHotkeys'
import CustomerMomentBar from '../components/CustomerMomentBar'
import DataFreshnessBar from '../components/DataFreshnessBar'
import CallPopBanner from '../components/CallPopBanner'
import OffersPanel from '../components/OffersPanel'
import PicSuggestions from '../components/PicSuggestions'
import PicHistoryModal from '../components/PicHistoryModal'
import PrescriptionOcrModal from '../components/PrescriptionOcrModal'
import ItemSearchWidget from '../components/ItemSearchWidget'
import QuickSellGrid from '../components/QuickSellGrid'
import StockLookupDrawer from '../components/StockLookupDrawer'
import BasketIntelPanel from '../components/BasketIntelPanel'
import POSCustomerModal from '../components/POSCustomerModal'
import CustomerTypePicker from '../components/CustomerTypePicker'
import SalespersonPicker from '../components/SalespersonPicker'
import UnitsQtyModal from '../components/UnitsQtyModal'
import usePosOrder, { CHANNELS, DOC_KINDS, PAY_METHODS, money, RECEIPT, CONTRACT_EMP_FIELDS } from '../hooks/usePosOrder'
import useGuidedFlow, { STAGE_TAB } from '../hooks/useGuidedFlow'
import { Badge, BatchBadge, Icon, WorkflowStep, ErrorState } from '../pos/design'

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
  const [showPic, setShowPic] = useState(false)
  const [showParked, setShowParked] = useState(false)
  const [showReceipt, setShowReceipt] = useState(false)
  const [guided, setGuided] = useState(false)
  const [showOcr, setShowOcr] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [showUnits, setShowUnits] = useState(false)   // Q shortcut → enter qty in strips/units
  const [stockItem, setStockItem] = useState(null)    // §37 network-stock lookup drawer (Find-Stock)
  // side panels collapse so the item grid gets full width (remembered per-device)
  const [modeOpen, setModeOpen] = useState(() => { try { return localStorage.getItem('pos_mode_open') !== '0' } catch { return true } })
  const [padOpen, setPadOpen] = useState(() => { try { return localStorage.getItem('pos_pad_open') !== '0' } catch { return true } })
  const toggleMode = () => setModeOpen(o => { const n = !o; try { localStorage.setItem('pos_mode_open', n ? '1' : '0') } catch { /* private */ } return n })
  const togglePad = () => setPadOpen(o => { const n = !o; try { localStorage.setItem('pos_pad_open', n ? '1' : '0') } catch { /* private */ } return n })
  // keyboard shortcuts are muted while any modal/overlay owns the screen
  const modalOpen = showCust || showPic || showParked || showReceipt || guided || showOcr || showHistory || showUnits || !!P.batchModal || !!P.couponModal || !!P.plan
  const histCustomerId = P.picCustomer?.id || P.customer?.id
  // Q → open the units (strips) entry for the selected line
  const openUnits = () => { if (P.selected >= 0 && P.selected < P.lines.length) setShowUnits(true) }
  usePosHotkeys(P, { enabled: !modalOpen, onOpenUnits: openUnits })
  return (
    <div dir="rtl" className="flex flex-col h-[calc(100vh-3.5rem)] bg-gray-100 text-[13px]">
      <style>{`.inp{width:100%;border:1px solid #d1d5db;border-radius:.3rem;padding:.2rem .4rem;font-size:12px}
        .pos-num::-webkit-inner-spin-button,.pos-num::-webkit-outer-spin-button{-webkit-appearance:none;margin:0}
        .pos-num{-moz-appearance:textfield}`}</style>
      <WorkflowBar P={P} guided={guided} onToggleGuided={() => setGuided(g => !g)} />
      <CallPopBanner onLoadCustomer={P.setCustomer} />
      <HeaderBand P={P} onOpenCust={() => setShowCust(true)} onOpenPic={() => setShowPic(true)} />
      <div className="flex flex-1 overflow-hidden">
        {/* channels + flags (collapsible → item lines get the width) */}
        {modeOpen
          ? <ModeColumn P={P} onCollapse={toggleMode} />
          : <Rail side="right" onClick={toggleMode} icon="👥" title="القنوات والخيارات" />}
        {/* center: tabs + grids + status + finalize footer */}
        <div className="flex-1 flex flex-col bg-white overflow-hidden">
          <Tabs P={P} />
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            {P.activeTab === 'items' && <ItemsTab P={P} onOpenOcr={() => setShowOcr(true)} onOpenHistory={histCustomerId ? () => setShowHistory(true) : null} onOpenUnits={(idx) => { P.setSelected(idx); setShowUnits(true) }} />}
            {P.activeTab === 'payment' && <div className="flex-1 min-h-0 overflow-auto"><PaymentTab P={P} /></div>}
            {P.activeTab === 'contract' && <div className="flex-1 min-h-0 overflow-auto"><ContractTab P={P} /></div>}
          </div>
          <StatusBar P={P} />
          <FooterBar P={P} onParked={() => setShowParked(true)} onReceipt={() => setShowReceipt(true)} />
        </div>
        {/* on-screen calculator (collapsible — keyboard entry needs no numpad) */}
        {padOpen
          ? <NumpadColumn P={P} onCollapse={togglePad} />
          : <Rail side="left" onClick={togglePad} icon="🔢" title="لوحة الأرقام" />}
      </div>
      {P.batchModal && <BatchModal P={P} />}
      {P.couponModal && <CouponModal P={P} />}
      {showCust && <POSCustomerModal onSelect={P.setCustomer} onClose={() => setShowCust(false)} />}
      {showPic && <POSCustomerModal onSelect={P.setPicCustomer} onClose={() => setShowPic(false)} />}
      {showParked && <ParkedModal P={P} onClose={() => setShowParked(false)} />}
      {showOcr && <PrescriptionOcrModal onAdd={P.addByBarcode} onClose={() => setShowOcr(false)} />}
      {showHistory && histCustomerId && (
        <PicHistoryModal customerId={histCustomerId} name={P.picCustomer?.name || P.customer?.name}
                         onAdd={P.addByBarcode} onClose={() => setShowHistory(false)} />
      )}
      {showUnits && P.selected >= 0 && P.lines[P.selected] && (
        <UnitsQtyModal P={P} i={P.selected} onClose={() => setShowUnits(false)}
                       onApply={() => focusPosCell(`qty-${P.selected}`)} />
      )}
      {stockItem && (
        <StockLookupDrawer item={stockItem} branchId={P.branch}
          customer={P.customer || P.picCustomer} picCode={P.picCustomer?.softech_pic || P.customer?.softech_pic}
          channel={P.channel} onClose={() => setStockItem(null)}
          onCreated={(kind) => P.setMsg(
            kind === 'demand' ? '✓ تم تسجيل طلب مفقود للعميل'
            : kind === 'reservation' ? '✓ تم إنشاء حجز للعميل'
            : kind === 'transfer' ? '✓ تم إنشاء طلب تحويل بين الفروع' : 'تم')} />
      )}
      {showReceipt && <ReceiptModal P={P} onClose={() => setShowReceipt(false)} />}
      {guided && <GuidedMode P={P} onClose={() => setGuided(false)} onOpenCust={() => setShowCust(true)} onOpenPic={() => setShowPic(true)} />}
      {P.plan && <PlanModal P={P} />}
    </div>
  )
}

/* ─────────────────── dry-run plan preview ─────────────────── */
function PlanModal({ P }) {
  const pl = P.plan
  const [showSql, setShowSql] = useState(false)
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => P.setPlan(null)}>
      <div dir="rtl" className="bg-white rounded-lg w-[46rem] max-w-[96vw] max-h-[90vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3 border-b flex items-center justify-between sticky top-0 bg-white">
          <div className="font-bold" style={{ color: '#022871' }}>🧾 معاينة الإرسال (وضع تجريبى — لن يُكتب في SOFTECH)</div>
          <button onClick={() => P.setPlan(null)} className="text-gray-400 hover:text-gray-700">✕</button>
        </div>
        <div className="p-5 space-y-3 text-[13px]">
          {pl.reservation_note && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 px-3 py-2 text-xs">⚠️ {pl.reservation_note}</div>
          )}
          {pl.points?.note && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-800 px-3 py-2 text-xs">🎁 {pl.points.note}</div>
          )}
          {/* lines */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs border">
              <thead className="bg-gray-100"><tr>
                {['الصنف', 'الكمية', 'سعر', 'خصم%', 'الإجمالي', 'الصلاحية', 'حالة'].map((c, i) => <th key={i} className="px-2 py-1 font-medium whitespace-nowrap">{c}</th>)}
              </tr></thead>
              <tbody>
                {(pl.lines || []).map((l, i) => (
                  <tr key={i} className="border-t text-center">
                    <td className="px-2 py-1 text-right">{l.itemcode}</td>
                    <td>{l.transqty}</td><td>{l.itemsaleprice}</td><td>{l.custdiscp}</td>
                    <td>{l.transprice_total}</td><td>{l.item_expiry || (l.is_reservation ? '—' : '')}</td>
                    <td>{l.is_reservation
                      ? <span className="text-[10px] bg-amber-100 text-amber-800 rounded px-1.5 py-0.5">حجز</span>
                      : <span className="text-[10px] bg-emerald-100 text-emerald-700 rounded px-1.5 py-0.5">بيع</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* payments */}
          {(pl.payments || []).length > 0 && (
            <div className="text-xs">
              <div className="font-medium mb-1">السداد</div>
              {pl.payments.map((p, i) => (
                <div key={i} className="flex justify-between border-b py-0.5"><span>نوع {p.paymenttype}</span><span>{p.paymentvalue}</span></div>
              ))}
            </div>
          )}
          {/* SQL (collapsible) */}
          {pl.sql && (
            <div>
              <button onClick={() => setShowSql(s => !s)} className="text-xs text-sky-700">{showSql ? '▾' : '▸'} عرض SQL ({Array.isArray(pl.sql) ? pl.sql.length : 1} عبارة)</button>
              {showSql && (
                <pre className="mt-1 bg-gray-900 text-gray-100 text-[11px] rounded p-2 overflow-x-auto max-h-56" dir="ltr">
                  {Array.isArray(pl.sql) ? pl.sql.join('\n') : pl.sql}
                </pre>
              )}
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t sticky bottom-0 bg-white flex justify-end">
          <button onClick={() => P.setPlan(null)} className="px-4 py-2 rounded-lg text-white text-sm" style={{ background: '#022871' }}>إغلاق</button>
        </div>
      </div>
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

// Pre-submit receipt share (client-side, mirrors the client-side print above). For a SAVED order the
// backend /pos-orders/<id>/share-whatsapp/ is the authoritative formatter (used in the Exception
// Center); here the order isn't persisted yet, so we format the on-screen preview — same data as print.
function shareReceiptWhatsApp(P, order) {
  const L = ['🧾 *إيصال بيع — صيدليات الرزيقي*']
  const cust = P.picCustomer?.name || P.customer?.name
  if (cust) L.push(`العميل: ${cust}`)
  if (P.docDate) L.push(`التاريخ: ${P.docDate}`)
  L.push('', `*الأصناف (${order.length}):*`)
  order.forEach((i, n) => {
    const l = P.lines[i]
    const net = (Number(l.item_sale_price) * (1 - Number(l.cust_discp) / 100)) * Number(l.qty)
    L.push(`${n + 1}. ${l.item_name} × ${Number(l.qty)} — ${net.toFixed(2)} ج.م`)
  })
  L.push('', `الإجمالي: ${Number(P.totals.gross).toFixed(2)} ج.م`)
  if (Number(P.totals.discount) > 0.005) L.push(`الخصم: ${Number(P.totals.discount).toFixed(2)} ج.م`)
  L.push(`*الصافي: ${Number(P.totals.net).toFixed(2)} ج.م*`, '', 'شكراً لتعاملكم مع صيدليات الرزيقي 🌿')
  const phone = String(P.picCustomer?.whatsapp_phone || P.picCustomer?.phone
    || P.customer?.whatsapp_phone || P.customer?.phone || '').replace(/\D/g, '')
  const text = encodeURIComponent(L.join('\n'))
  window.open(phone ? `https://wa.me/${phone}?text=${text}` : `https://wa.me/?text=${text}`,
              '_blank', 'noopener,noreferrer')
}

function ReceiptModal({ P, onClose }) {
  // the printed receipt has its OWN sort (independent of the on-screen grid) — default = the
  // data-entry / prescription order, but the pharmacist can print alphabetically etc. for pickup.
  const [rsKey, setRsKey] = useState('entry')
  const [rsDir, setRsDir] = useState('asc')
  const rOrder = useMemo(() => orderedIndices(P.lines, rsKey, rsDir), [P.lines, rsKey, rsDir])
  const cycle = (k) => {
    if (k === 'entry') { setRsKey('entry'); setRsDir('asc'); return }
    if (rsKey === k) setRsDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setRsKey(k); setRsDir('asc') }
  }
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 print:bg-white" onClick={onClose}>
      <div dir="rtl" id="pos-receipt" className="bg-white rounded-lg p-5 w-[22rem] max-h-[88vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="text-center font-bold">{RECEIPT.headers[0]}</div>
        {RECEIPT.headers.slice(1).map((h, i) => (
          <div key={i} className="text-center text-[11px] text-gray-600">{h}</div>
        ))}
        <div className="text-center text-xs text-gray-500 mt-1 mb-2">إيصال بيع — {P.docDate}</div>
        <div className="text-xs mb-1">العميل: {P.customer?.name || 'Walk-In Customer'}</div>
        {P.picCustomer && <div className="text-xs mb-1">عميل PIC: {P.picCustomer.name}{P.picCustomer.softech_pic ? ` (${P.picCustomer.softech_pic})` : ''}{P.picCustomer.phone ? ` · ☎ ${P.picCustomer.phone}` : ''}</div>}
        {/* Print Employee Name of Contract Customer = ON */}
        {P.isClaim && P.claim?.patientname && (
          <div className="text-xs mb-1">اسم المريض: {P.claim.patientname}{P.claim.patientno ? ` (${P.claim.patientno})` : ''}</div>
        )}
        <div className="text-xs mb-1">مسؤول البيع: {P.salespersonName || '—'}{P.salesperson ? ` (${P.salesperson})` : ''}</div>
        {/* print-order picker — hidden on the printout itself */}
        <div className="flex items-center gap-1 flex-wrap text-[10px] mt-1 print:hidden">
          <span className="text-gray-400">ترتيب الطباعة:</span>
          {LINE_SORTS.map(([k, label, ic]) => {
            const active = rsKey === k
            return (
              <button key={k} onClick={() => cycle(k)} title={k === 'entry' ? 'ترتيب إدخال الأصناف (تسلسل الروشتة)' : `فرز حسب ${label}`}
                className={`px-1.5 py-0.5 rounded border ${active ? 'text-white border-transparent' : 'bg-white text-gray-600 hover:bg-gray-100'}`}
                style={active ? { background: '#022871' } : undefined}>
                {ic}{active && k !== 'entry' ? (rsDir === 'asc' ? '▲' : '▼') : ''}
              </button>
            )
          })}
        </div>
        <table className="w-full text-xs border-t border-b my-2">
          <tbody>
            {rOrder.map(i => { const l = P.lines[i]; return (
              <tr key={i}><td className="py-0.5">{l.item_name}</td><td className="text-center">{Number(l.qty)}×</td><td className="text-left">{money((l.item_sale_price * (1 - l.cust_discp / 100)) * l.qty)}</td></tr>
            ) })}
          </tbody>
        </table>
        <div className="text-xs flex justify-between"><span>الإجمالي</span><span>{money(P.totals.gross)}</span></div>
        <div className="text-xs flex justify-between text-orange-600"><span>الخصم</span><span>{money(P.totals.discount)}</span></div>
        <div className="text-sm flex justify-between font-bold"><span>الصافي</span><span>{money(P.totals.net)}</span></div>
        {P.loyalty?.points_balance != null && <div className="text-xs text-center mt-2 text-emerald-700">نقاط الولاء: {P.loyalty.points_balance}</div>}
        {P.pointsInfo.eligible && P.pointsInfo.enrolled && (P.picCustomer?.softech_pic || P.customer?.softech_pic) && (
          <div className="text-[11px] text-center mt-1 text-emerald-700">🎁 عميل مسجّل بنظام النقاط — تُحتسب عند إنهاء الكاشير</div>
        )}
        <div className="border-t mt-3 pt-2 space-y-0.5">
          {RECEIPT.footers.map((f, i) => (
            <div key={i} className="text-center text-[10px] text-gray-500 leading-tight">{f}</div>
          ))}
        </div>
        <div className="flex gap-2 mt-4 print:hidden">
          <button onClick={onClose} className="flex-1 py-2 rounded border">إغلاق</button>
          <button onClick={() => shareReceiptWhatsApp(P, rOrder)}
                  className="flex-1 py-2 rounded border border-green-500 text-green-700 hover:bg-green-50">📱 واتساب</button>
          <button onClick={() => window.print()} className="flex-1 py-2 rounded bg-blue-600 text-white">🖨 طباعة</button>
        </div>
      </div>
    </div>
  )
}

/* ─────────────────── workflow "story" bar (reactive) ─────────────────── */
// step.key → semantic icon (design system); unmapped keys fall back to the done-check / bare node.
const STEP_ICON = { customer: 'usercheck', pic: 'usercheck', items: 'package', batch: 'package',
                    payment: 'tag', contract: 'rx', claim: 'rx', delivery: 'truck', offers: 'tag', review: 'check' }
const WF_STATE = { active: 'current', blocked: 'error', done: 'done', todo: 'todo' }
const WF_TABS = ['items', 'payment', 'contract']
function WorkflowBar({ P, guided, onToggleGuided }) {
  const wf = P.workflow
  const go = s => { if (WF_TABS.includes(s.tab)) P.setActiveTab(s.tab) }
  return (
    <div className="bg-white border-b px-3 py-1 shadow-sm">
      <div className="flex items-center gap-1 overflow-x-auto">
        <button onClick={onToggleGuided} title="الوضع الموجّه — خطوة بخطوة"
          className={`shrink-0 flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition ${guided ? 'text-white border-transparent' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
          style={guided ? { background: '#022871' } : undefined}>
          🧭 <span className="whitespace-nowrap">موجّه</span>
        </button>
        <span className="w-px h-4 bg-gray-200 shrink-0" />
        {/* adaptive (§34): irrelevant stages disappear — skipped steps are not rendered at all. */}
        {(() => {
          const steps = wf.steps.filter(s => s.status !== 'skip')
          return steps.map((s, i) => (
            <WorkflowStep key={s.key} icon={STEP_ICON[s.key]} label={s.label}
              state={WF_STATE[s.status] || 'todo'}
              onClick={() => go(s)} last={i === steps.length - 1} />
          ))
        })()}
        <div className="flex-1 min-w-2" />
        {wf.next
          ? <div className="shrink-0 text-[11px] text-white rounded-full px-2 py-0.5" style={{ background: '#022871' }}>
              التالى: {wf.next.label}{wf.next.hint ? ` — ${wf.next.hint}` : ''}
            </div>
          : <div className="shrink-0 text-[11px] bg-emerald-600 text-white rounded-full px-2 py-0.5">جاهز للحفظ ✓</div>}
        <div className="shrink-0 text-[10px] text-gray-500 w-8 text-left tabular-nums">{wf.progress}%</div>
        <div className="h-1 w-16 bg-gray-100 rounded-full overflow-hidden shrink-0">
          <div className="h-full rounded-full transition-all duration-300"
               style={{ width: `${wf.progress}%`, background: 'linear-gradient(90deg,#3880bb,#10b981)' }} />
        </div>
      </div>
      {wf.advisories.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {wf.advisories.map((a, i) => {
            const tone = a.level === 'error' ? 'bg-red-50 text-red-700 border-red-200'
                       : a.level === 'warn' ? 'bg-amber-50 text-amber-700 border-amber-200'
                       : 'bg-sky-50 text-sky-700 border-sky-200'
            const clickable = a.action || WF_TABS.includes(a.tab)
            const onClick = () => {
              if (a.action === 'applyAllSuggested') P.applyAllSuggested()
              else if (WF_TABS.includes(a.tab)) P.setActiveTab(a.tab)
            }
            return (
              <button key={i} onClick={onClick}
                className={`inline-flex items-center gap-1 text-[11px] border rounded px-2 py-1 ${tone} ${clickable ? 'hover:brightness-95 cursor-pointer' : 'cursor-default'}`}>
                <Icon name={a.level === 'error' ? 'block' : a.level === 'warn' ? 'alert' : 'info'} size={12} /> {a.text}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* ─────────────────── guided focus mode (wizard) ─────────────────── */
// One panel at a time over a dimmed power-screen. Stages reuse the same tab panels and the
// same reactive engine (via useGuidedFlow), so switching in/out never loses or forks state.
function GuidedMode({ P, onClose, onOpenCust, onOpenPic }) {
  const wf = P.workflow
  const { stages, safeIdx, stage, isLast, stStatus, setIdx, goNext, goPrev } = useGuidedFlow(P)
  const stageAdvisories = wf.advisories.filter(a => a.tab === STAGE_TAB[stage.key])

  return (
    <div className="fixed inset-0 z-[45] flex flex-col bg-slate-900/60 backdrop-blur-sm" onClick={onClose}>
      <div dir="rtl" onClick={e => e.stopPropagation()}
           className="m-auto bg-white rounded-2xl shadow-2xl w-[min(56rem,95vw)] max-h-[92vh] flex flex-col overflow-hidden">
        {/* header: stage rail + progress + close */}
        <div className="px-5 pt-4 pb-3 border-b" style={{ background: 'linear-gradient(180deg,#f8fafc,#fff)' }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-sm font-bold" style={{ color: '#022871' }}>
              🧭 الوضع الموجّه
              <span className="text-xs font-normal text-gray-400">({safeIdx + 1} / {stages.length})</span>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-sm flex items-center gap-1">
              الوضع الكامل ✕
            </button>
          </div>
          <div className="flex items-center gap-1.5 overflow-x-auto">
            {stages.map((s, i) => {
              const st = stStatus(s)
              const active = i === safeIdx
              const ring = active ? 'text-white border-transparent'
                : st === 'done' ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                : st === 'blocked' ? 'border-red-300 bg-red-50 text-red-700'
                : 'border-gray-200 bg-white text-gray-500'
              return (
                <div key={s.key} className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => setIdx(i)}
                    className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${ring}`}
                    style={active ? { background: '#022871' } : undefined}>
                    <span>{s.icon}</span><span className="whitespace-nowrap font-medium">{s.title}</span>
                    {!active && st === 'done' && <span className="font-bold">✓</span>}
                    {!active && st === 'blocked' && <span className="font-bold">!</span>}
                  </button>
                  {i < stages.length - 1 && <span className="w-4 h-px bg-gray-200" />}
                </div>
              )
            })}
          </div>
        </div>

        {/* the one active panel */}
        <div className="flex-1 overflow-auto p-4 bg-white">
          {stage.key === 'customer' && <GuidedCustomer P={P} onOpenCust={onOpenCust} onOpenPic={onOpenPic} />}
          {stage.key === 'items' && <ItemsTab P={P} />}
          {stage.key === 'claim' && <ContractTab P={P} />}
          {stage.key === 'payment' && <GuidedPayment P={P} />}
          {stageAdvisories.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {stageAdvisories.map((a, i) => {
                const tone = a.level === 'error' ? 'bg-red-50 text-red-700 border-red-200'
                  : a.level === 'warn' ? 'bg-amber-50 text-amber-700 border-amber-200'
                  : 'bg-sky-50 text-sky-700 border-sky-200'
                return (
                  <button key={i} onClick={() => { if (a.action === 'applyAllSuggested') P.applyAllSuggested() }}
                    className={`text-xs border rounded px-2 py-1 ${tone} ${a.action ? 'hover:brightness-95' : 'cursor-default'}`}>
                    {a.level === 'error' ? '⛔' : a.level === 'warn' ? '⚠️' : 'ℹ️'} {a.text}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* footer: net + back/next or submit */}
        <div className="border-t px-5 py-3 flex items-center gap-3 bg-gray-50">
          <span className="flex items-center gap-1.5 text-white rounded-lg px-3 py-1 text-sm" style={{ background: '#022871' }}>الصافي <b className="text-base tabular-nums">{money(P.totals.net)}</b></span>
          {P.msg && <div className="text-xs text-gray-500 truncate max-w-[16rem]">{P.msg}</div>}
          <div className="flex-1" />
          <button onClick={goPrev} disabled={safeIdx === 0}
                  className="px-4 py-2 rounded-lg border text-sm disabled:opacity-40">‹ السابق</button>
          {!isLast
            ? <button onClick={goNext}
                      className="px-5 py-2 rounded-lg text-white text-sm font-medium" style={{ background: '#022871' }}>
                التالى ›
              </button>
            : <div className="flex gap-2">
                <button onClick={() => P.submit(false)} disabled={P.busy}
                        className="px-4 py-2 rounded-lg border text-sm disabled:opacity-40">🧾 معاينة (تجريبى)</button>
                <button onClick={() => P.submit(true)} disabled={P.busy || !wf.ready}
                        className="px-5 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium disabled:opacity-40">
                  {P.busy ? '…' : '✓ إرسال للكاشير'}
                </button>
              </div>}
        </div>
      </div>
    </div>
  )
}

// focused customer+channel+seller panel for the guided wizard (subset of the header band)
function GuidedCustomer({ P, onOpenCust, onOpenPic }) {
  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="grid grid-cols-2 gap-3">
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
      </div>
      <div className="flex gap-1 items-start">
        <div className="flex-1"><CustomerTypePicker P={P} onOpenPic={onOpenPic} /></div>
        <button onClick={onOpenCust} title="دليل العملاء الأفراد (بحث/إضافة)"
                className="px-2 py-1.5 mt-4 border rounded bg-gray-50 shrink-0 text-sm">…</button>
      </div>
      <F label="مسؤول البيع (كود/اسم)"><SalespersonPicker P={P} className="inp" /></F>
    </div>
  )
}

// payment + review panel for the guided wizard
function GuidedPayment({ P }) {
  return (
    <div className="max-w-2xl mx-auto space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
        {[['الإجمالي', P.totals.gross], ['الخصم', P.totals.discount], ['الضريبة', P.totals.tax], ['الصافي', P.totals.net]].map(([l, v], i) => (
          <div key={i} className={`rounded-lg border p-2 ${l === 'الصافي' ? 'bg-emerald-50 border-emerald-200' : 'bg-gray-50'}`}>
            <div className="text-[11px] text-gray-500">{l}</div>
            <div className={`font-bold ${l === 'الصافي' ? 'text-emerald-700' : ''}`}>{money(v)}</div>
          </div>
        ))}
      </div>
      {P.isClaim && (
        <div className="grid grid-cols-3 gap-2">
          <F label="خصم العميل %"><input value={P.totals.custDiscPct} readOnly className="inp bg-gray-50" /></F>
          <F label="ما يسدده المريض"><input type="number" step="0.01" value={P.patientPayment} placeholder={P.totals.net}
                onChange={e => P.setPatientCopay(e.target.value)} className="inp" /></F>
          <F label="يتحمله التعاقد"><input value={P.totals.claimAmount} readOnly className="inp bg-amber-50" /></F>
        </div>
      )}
      <PaymentTab P={P} />
    </div>
  )
}

/* (PIC picker moved INTO CustomerTypePicker as stage ③ of the three-level cascade.) */

/* (PicSuggestions extracted to components/PicSuggestions.jsx — shared web + mobile.) */

/* ───────────────────────── header band ───────────────────────── */
// Compact icon toolbar: the whole transaction header on two dense lines so the item grid gets
// the height. Full field names live in tooltips; the rarely-touched fields are behind «تفاصيل».
function HeaderBand({ P, onOpenCust, onOpenPic }) {
  const [moreOpen, setMoreOpen] = useState(() => { try { return localStorage.getItem('pos_hdr_more') === '1' } catch { return false } })
  const toggleMore = () => setMoreOpen(o => { const n = !o; try { localStorage.setItem('pos_hdr_more', n ? '1' : '0') } catch { /* private */ } return n })
  const showMore = moreOpen || P.isClaim   // claim/insurance need the co-pay + contract split fields
  const sel = 'h-8 border rounded px-1.5 text-xs bg-white min-w-0'
  return (
    <div className="bg-white border-b px-3 py-1.5 flex flex-col gap-1.5">
      {/* Row 1 — context toolbar */}
      <div className="flex items-center gap-1.5 flex-wrap text-xs">
        <span title="مبيعات فرع" className="text-sm">🏢</span>
        <select value={P.branch} onChange={e => P.setBranch(e.target.value)} className={`${sel} max-w-[11rem]`} title="مبيعات فرع">
          <option value="">فرع…</option>
          {P.branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
        </select>
        <span title="من حساب مخزن" className="text-sm">🏬</span>
        <select value={P.storeCode} onChange={e => P.setStoreCode(e.target.value)} className={`${sel} max-w-[9rem]`} title="من حساب مخزن (④)"
                data-pos-flow="store" {...posFlow('search', 'flow:pic')}>
          {!P.stores?.length && <option value={P.storeCode}>{P.storeCode || 'مخزن…'}</option>}
          {(P.stores || []).map(s => <option key={s.storecode} value={s.storecode}>{s.storename || s.storecode}{s.default ? ' ★' : ''}</option>)}
        </select>
        <span title="مسؤول البيع" className="text-sm">👤</span>
        <div className="w-40"><SalespersonPicker P={P} className={`${sel} w-full`} /></div>
        <span className="w-px h-5 bg-gray-200 mx-0.5" />
        <span title="نوع المستند" className="text-sm">🧾</span>
        <select value={P.docKind} onChange={e => P.setDocKind(e.target.value)} className={sel} title="نوع المستند">
          {DOC_KINDS.map(d => <option key={d.value} value={d.value}>{d.label} ({d.code})</option>)}
        </select>
        {P.docKind === 'return' && (
          <span className="flex items-center gap-1 rounded bg-red-50 border border-red-200 px-1.5 py-0.5">
            <span title="مرتجع للفاتورة الأصلية" className="text-xs text-[#ea0000] shrink-0">↩ فاتورة</span>
            <input value={P.returnInvoice} onChange={e => P.setReturnInvoice(e.target.value)}
                   onKeyDown={e => { if (e.key === 'Enter') P.loadReturn() }}
                   className={`${sel} w-24`} placeholder="رقم الفاتورة" title="رقم الفاتورة الأصلية (المنتهية)" />
            <button type="button" onClick={() => P.loadReturn()} disabled={P.busy}
                    className="h-7 px-2 rounded bg-[#022871] text-white text-xs disabled:opacity-50 shrink-0">تحميل</button>
            {P.returnMeta && <span className="text-[11px] text-emerald-700 tabular-nums shrink-0"
                                   title={`تاريخ الفاتورة ${P.returnMeta.docdate}`}>
              ✓ {P.returnMeta.count} صنف · {P.returnMeta.total} ج
              {P.returnMeta.fullOnly && <span className="text-[#ea0000]" title="التعاقد يسمح بإرتجاع كامل الفاتورة فقط"> · 🔒 كامل</span>}
              {P.returnMeta.blockedCount > 0 && <span className="text-amber-600" title="أصناف محجوزة مُسلّمة مستبعَدة — اعكس التسليم أولاً"> · ⚠{P.returnMeta.blockedCount} محجوز</span>}
            </span>}
          </span>
        )}
        <span title="أسلوب السداد" className="text-sm">💳</span>
        <select value={P.paymentMethod} onChange={e => P.setPaymentMethod(e.target.value)} className={sel} title="أسلوب السداد">
          {PAY_METHODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
        <span title="تاريخ المستند" className="text-sm">📅</span>
        <input type="date" value={P.docDate} onChange={e => P.setDocDate(e.target.value)} className={`${sel} max-w-[8.5rem]`} title="تاريخ المستند" />
        <div className="flex-1" />
        {/* Freshness of the mirror data POS prices/stock/customer lookups rely on */}
        <DataFreshnessBar compact domains={['stock', 'catalog', 'customers']} />
        {P.loyalty?.points_balance != null && <span className="text-emerald-700 tabular-nums" title="نقاط الولاء">🎁 {P.loyalty.points_balance}</span>}
        <button onClick={toggleMore} title="حقول إضافية (خصم فكة · مسلسل · ملاحظات · ما يسدده المريض)"
                className="h-8 px-2 rounded border text-xs text-gray-500 hover:bg-gray-50 shrink-0">{showMore ? '▾' : '⋯'} تفاصيل</button>
      </div>

      {/* Row 2 — three-level customer cascade (dense, single line) */}
      <div className="flex items-center gap-1.5">
        <span title="العميل" className="text-sm shrink-0">🧑‍⚕️</span>
        <div className="flex-1 min-w-0"><CustomerTypePicker P={P} dense onOpenPic={onOpenPic} flow={{
          type: posFlow('flow:custname', null),                 // ① نوع العميل → ② الإسم
          name: posFlow('flow:pic', 'flow:custtype', true),     // ② الإسم → ③ PIC (Enter picks from the list)
          pic: posFlow('flow:store', 'flow:custname'),          // ③ PIC → ④ المخزن
        }} /></div>
        <button onClick={onOpenCust} title="دليل العملاء الأفراد (بحث/إضافة)"
                className="h-8 px-2 border rounded bg-gray-50 hover:bg-gray-100 shrink-0 text-sm">📇</button>
      </div>

      {/* details — collapsed by default so the grid keeps the height */}
      {showMore && (
        <div className="flex items-center gap-2 flex-wrap text-xs border-t pt-1.5">
          <label title="خصم فكة" className="flex items-center gap-1">💰<input type="number" step="0.01" value={P.changeDiscount} onChange={e => P.setChangeDiscount(e.target.value)} className={`${sel} w-20`} /></label>
          <label title="مسلسل صرف" className="flex items-center gap-1">#<input value={P.dispenseSerial} readOnly className={`${sel} w-24 bg-gray-50`} placeholder="تلقائى" /></label>
          <label title="ملاحظات" className="flex items-center gap-1">📝<input value={P.notes} onChange={e => P.setNotes(e.target.value)}
                 data-pos-flow="notes" {...posFlow('search', 'flow:store')} className={`${sel} w-44`} /></label>
          <label title="خصم العميل %" className="flex items-center gap-1">٪<input value={P.totals.custDiscPct} readOnly className={`${sel} w-16 bg-gray-50`} /></label>
          <label title="ما يسدده المريض" className="flex items-center gap-1">💳<input type="number" step="0.01"
                 value={P.isClaim ? P.patientPayment : P.totals.patientPays} placeholder={P.totals.net} readOnly={!P.isClaim}
                 onChange={e => P.setPatientCopay(e.target.value)} className={`${sel} w-24` + (P.isClaim ? '' : ' bg-gray-50')} /></label>
          {P.isClaim && <label title="يتحمله التعاقد" className="flex items-center gap-1">🏥<input value={P.totals.claimAmount} readOnly className={`${sel} w-24 bg-amber-50`} /></label>}
        </div>
      )}
    </div>
  )
}

// Thin rail shown in place of a collapsed side panel — click to expand.
function Rail({ side, onClick, icon, title }) {
  return (
    <button onClick={onClick} title={`إظهار ${title}`}
            className={`w-7 shrink-0 bg-gray-50 ${side === 'right' ? 'border-l' : 'border-r'} flex flex-col items-center pt-2 gap-2 text-gray-500 hover:bg-gray-100`}>
      <span className="text-sm">{side === 'right' ? '›' : '‹'}</span>
      <span className="text-sm">{icon}</span>
      <span className="text-[10px] whitespace-nowrap [writing-mode:vertical-rl] rotate-180">{title}</span>
    </button>
  )
}

function ModeColumn({ P, onCollapse }) {
  const Mode = ({ ch, hot }) => (
    <button onClick={() => P.setCustType(ch.value)}
            className={`w-full text-right px-3 py-2 rounded border text-xs mb-1 transition ${P.custType === ch.value ? 'text-white border-transparent' : 'bg-white hover:bg-gray-100'}`}
            style={P.custType === ch.value ? { background: '#022871' } : undefined}>
      {hot && <span className="opacity-70 ml-1">{hot} =</span>} {ch.label}
    </button>
  )
  const Chk = ({ v, set, label }) => (
    <label className="flex items-center gap-1.5 text-xs mb-1.5">
      <input type="checkbox" checked={v} onChange={e => set(e.target.checked)} /> {label}
    </label>
  )
  // channel allowed if the (server-filtered) type list still carries it (empty = loading → show all)
  const chanOk = (v) => !P.custTypes?.length || P.custTypes.some(t => t.channel === v || t.key === v)
  return (
    <div className="w-44 bg-gray-50 border-l p-2 overflow-auto">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] font-semibold text-gray-500">القناة والخيارات</span>
        <button onClick={onCollapse} title="طيّ العمود لتوسيع الأصناف" className="text-gray-400 hover:text-gray-700 text-sm">›</button>
      </div>
      {chanOk('cash') && <Mode ch={{ value: 'cash', label: 'مبيعات نقدى' }} hot="Ctrl+F2" />}
      {chanOk('delivery') && <Mode ch={{ value: 'delivery', label: 'توصيل منزلى' }} hot="Ctrl+F3" />}
      {chanOk('contract') && <Mode ch={{ value: 'contract', label: 'مبيعات تعاقد' }} />}
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
        <div className="text-2xl font-bold tabular-nums" style={{ color: '#022871' }}>{money(P.totals.net)}</div>
      </div>
      <KeyboardLegend />
    </div>
  )
}

function Tabs({ P }) {
  const T = ({ id, label }) => (
    <button onClick={() => P.setActiveTab(id)}
            className={`px-4 py-2 text-sm border-b-2 transition ${P.activeTab === id ? 'font-semibold' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
            style={P.activeTab === id ? { borderColor: '#022871', color: '#022871' } : undefined}>
      {label}
    </button>
  )
  return (
    <div className="flex border-b bg-gray-50">
      <T id="items" label="🛒 الأصناف" />
      <T id="payment" label={`💳 السداد (${P.tenders.length})`} />
      <T id="contract" label="📋 بيانات التعاقد" />
    </div>
  )
}

/* ── Line-grid sorting (display-only) ─────────────────────────────────────────
 * The canonical P.lines order IS the data-entry (prescription) sequence and is exactly what
 * gets submitted to SOFTECH — sorting NEVER mutates it. Each view (grid, receipt) picks its own
 * sort and can always snap back to 'entry'. orderedIndices returns canonical indices in display
 * order, so every rendered row keeps its REAL index for setLine / removeLine / data-pos-cell /
 * selection — nothing about editing or the SOFTECH payload changes when you re-sort. */
export const LINE_SORTS = [
  ['entry', 'ترتيب الإدخال', '↩'],
  ['name', 'الاسم', '🔤'],
  ['qty', 'الكمية', '🔢'],
  ['price', 'السعر', '💲'],
  ['disc', 'الخصم', '٪'],
  ['total', 'الصافي', '∑'],
]
const _lineNet = (l) => +(l.item_sale_price * (1 - l.cust_discp / 100)) * l.qty
export function orderedIndices(lines, key = 'entry', dir = 'asc') {
  const idx = lines.map((_, i) => i)
  if (key === 'entry' || !key) return idx
  const val = {
    name: i => (lines[i].item_name || '').toString(),
    qty: i => Number(lines[i].qty) || 0,
    price: i => Number(lines[i].item_sale_price) || 0,
    disc: i => Number(lines[i].cust_discp) || 0,
    total: i => _lineNet(lines[i]),
  }[key]
  if (!val) return idx
  const cmp = key === 'name'
    ? (a, b) => val(a).localeCompare(val(b), 'ar')
    : (a, b) => val(a) - val(b)
  // Array.prototype.sort is stable → rows with an equal key keep their data-entry order.
  return idx.sort((a, b) => (dir === 'desc' ? -cmp(a, b) : cmp(a, b)))
}

/* ───────────────────────── Items tab ───────────────────────── */
function ItemsTab({ P, onOpenOcr, onOpenHistory, onOpenUnits }) {
  // display-only sort of the line grid (canonical P.lines is untouched → prescription order kept)
  const [sortKey, setSortKey] = useState('entry')
  const [sortDir, setSortDir] = useState('asc')
  const order = useMemo(() => orderedIndices(P.lines, sortKey, sortDir), [P.lines, sortKey, sortDir])
  const toggleSort = (k) => {
    if (!k) return
    if (k === 'entry') { setSortKey('entry'); setSortDir('asc'); return }
    if (sortKey === k) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('asc') }
  }
  // space-hungry helpers collapsed by default so the grid gets the height (remembered per-device)
  const [toolsOpen, setToolsOpen] = useState(() => { try { return localStorage.getItem('pos_tools_open') === '1' } catch { return false } })
  const [intelOpen, setIntelOpen] = useState(() => { try { return localStorage.getItem('pos_intel_open') === '1' } catch { return false } })
  const toggleTools = () => setToolsOpen(o => { const n = !o; try { localStorage.setItem('pos_tools_open', n ? '1' : '0') } catch { /* private mode */ } return n })
  const toggleIntel = () => setIntelOpen(o => { const n = !o; try { localStorage.setItem('pos_intel_open', n ? '1' : '0') } catch { /* private mode */ } return n })
  // Full SOFTECH In-Direct POS line grid (17 cols). العبوة = the item's UNIT (علبة/شريط) — NOT a
  // bonus (POS has no bonus field). Sort buttons only where a numeric/text order is meaningful.
  const COLS = [
    [null, 'الباركود'], [null, 'الكود'], ['name', 'الصنف'],
    [null, 'رصيد صلاحية'], [null, 'رصيد متاح'], [null, 'ت.الصلاحية'], [null, 'رقم الباتش'],
    [null, 'العبوة'], ['qty', 'الكمية Q'], [null, 'Unit Price'], ['price', 'Pkg Price'],
    [null, 'ض.ق %'], ['disc', 'خصم %'], [null, 'مبلغ الخصم'], [null, 'م.ض.ق.م'], [null, 'سعر العبوة'],
    ['total', 'الإجمالي'], [null, ''],
  ]
  // After ANY add appends a line, jump focus to its qty cell (SOFTECH Enter→qty flow).
  const prevLen = useRef(P.lines.length)
  useEffect(() => {
    if (P.lines.length > prevLen.current) {
      const last = P.lines.length - 1
      P.setSelected(last)   // select the new line so F4/arrows act on it immediately
      setTimeout(() => {
        const el = document.querySelector(`[data-pos-cell="qty-${last}"]`)
        if (el) { el.focus(); el.select?.() }
      }, 0)
    }
    prevLen.current = P.lines.length
  }, [P.lines.length])
  const custId = P.picCustomer?.id || P.customer?.id
  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── compact top: moment bar + search + collapsible quick tools + sort bar ── */}
      <div className="shrink-0 px-2 pt-2">
        {custId && (
          <div className="mb-2 flex items-start gap-2">
            <div className="flex-1"><CustomerMomentBar customerId={custId} /></div>
            {onOpenHistory && (
              <button onClick={onOpenHistory} title="سجل معاملات العميل السابقة (كل الفواتير)"
                      className="shrink-0 self-center text-[11px] px-2 py-1 rounded border border-indigo-200 bg-white text-indigo-700 hover:bg-indigo-50 whitespace-nowrap">📜 السجل</button>
            )}
          </div>
        )}
        <div className="flex gap-2 mb-2">
          <div className="flex-1" id="pos-item-search"><ItemSearchWidget onSelect={P.addItem} placeholder="ابحث بالاسم / الكود / الباركود… (F2 إضافة · Ctrl+F1 بحث متقدم)" /></div>
          <button onClick={onOpenOcr} title="إدخال ذكي — قراءة روشتة أو تسجيل صوتي"
                  className="px-2 rounded text-white text-xs whitespace-nowrap self-start mt-1" style={{ background: '#022871' }}>📷🎤 ذكي</button>
          {Object.values(P.suggest.map || {}).some(v => v != null) &&
            <button onClick={P.applyAllSuggested} className="px-2 rounded bg-emerald-600 text-white text-xs whitespace-nowrap self-start mt-1">تطبيق الخصم المقترح</button>}
        </div>
        {/* quick tools (favorites + top-sellers) — collapsed by default so the grid gets the height */}
        <div className="mb-1">
          <button onClick={toggleTools} className="text-[11px] text-gray-500 hover:text-gray-700 flex items-center gap-1">
            {toolsOpen ? '▾' : '▸'} أدوات سريعة{P.favorites.length ? ` · ⭐ ${P.favorites.length}` : ''} · الأكثر مبيعًا
          </button>
          {toolsOpen && (
            <div className="mt-1">
              {P.favorites.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-2">
                  {P.favorites.map(f => (
                    <button key={f.softech_id} onClick={() => P.addItem(f)}
                            className="px-2 py-1 rounded bg-amber-50 border border-amber-200 text-[11px]">⭐ {f.name?.slice(0, 22)}</button>
                  ))}
                </div>
              )}
              <QuickSellGrid branchId={P.branch} onSelect={P.addItem} onFindStock={setStockItem} />
            </div>
          )}
        </div>
        {/* sort bar — display-only; canonical (data-entry) order is always one click away */}
        <div className="flex items-center gap-1.5 flex-wrap text-[11px] pb-1.5">
          <span className="text-gray-400">الترتيب:</span>
          {LINE_SORTS.map(([k, label, ic]) => {
            const active = sortKey === k
            return (
              <button key={k} onClick={() => toggleSort(k)} title={k === 'entry' ? 'العودة لترتيب إدخال الأصناف (تسلسل الروشتة)' : `فرز حسب ${label}`}
                className={`px-2 py-0.5 rounded-full border transition ${active ? 'text-white border-transparent' : 'bg-white text-gray-600 hover:bg-gray-100'}`}
                style={active ? { background: '#022871' } : undefined}>
                {ic} {label}{active && k !== 'entry' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
              </button>
            )
          })}
          <span className="flex-1" />
          <span className="text-gray-400 tabular-nums">🧾 {P.lines.length} صنف</span>
        </div>
      </div>

      {/* ── the line grid: the star — its own scroll + a sticky, sortable header so hundreds of
             items stay readable while the column heads and the totals footer stay put ── */}
      <div className="flex-1 min-h-0 overflow-auto border-t">
        <table className="w-full text-xs">
          <thead className="text-white sticky top-0 z-10" style={{ background: '#022871' }}>
            <tr>{COLS.map(([key, label], ci) => (
              <th key={ci} className={`px-2 py-1.5 whitespace-nowrap font-medium text-[11px] ${ci === 2 ? 'text-right min-w-[210px]' : 'text-center'}`}>
                {key
                  ? <button onClick={() => toggleSort(key)} title="فرز" className="inline-flex items-center gap-1 hover:opacity-80">
                      {label}<span className="opacity-60">{sortKey === key ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}</span>
                    </button>
                  : label}
              </th>
            ))}</tr>
          </thead>
          <tbody>
            {order.map(i => {
              const l = P.lines[i]
              const net = +(l.item_sale_price * (1 - l.cust_discp / 100)) * l.qty
              const taxAmt = l.sale_tax_pct ? net - net / (1 + l.sale_tax_pct / 100) : 0
              const sel = P.selected === i
              const discOn = Number(l.cust_discp) > 0
              return (
                <tr key={i} onClick={() => P.setSelected(i)}
                    className={`border-b border-gray-100 cursor-pointer ${sel ? 'bg-sky-50 shadow-[inset_-3px_0_0_0_#022871]' : 'hover:bg-gray-50'}`}>
                  <Td className="tabular-nums text-gray-400">{l.barcode || '—'}</Td>
                  <Td className="tabular-nums text-gray-600">{l.softech_itemcode}</Td>
                  {/* ── الصنف: favorite + name + status chips ── */}
                  <td className="px-2 py-1.5 text-right min-w-[210px]">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <button onClick={e => { e.stopPropagation(); P.toggleFavorite(l) }} title="مفضّلة"
                              className="text-sm leading-none shrink-0">{P.isFavorite(l.softech_itemcode) ? '⭐' : '☆'}</button>
                      <span className="font-semibold text-[13px] text-gray-800 leading-tight">{l.item_name}</span>
                      {l.is_reservation && <Badge meaning="reservation" size="xs" label="حجز" title="غير متوفر — يُضاف كحجز" />}
                      {l.not_stockable && <Badge tone="info" icon="pill" size="xs" label="خدمي" title="صنف غير مخزون (خدمي) — بلا رصيد أو تشغيلة أو حجز" />}
                      {discOn && !P.discountLocked && <Badge tone="warn" icon="tag" size="xs" label={`−${l.cust_discp}%`} title="خصم مطبَّق" />}
                    </div>
                  </td>
                  <Td className="tabular-nums text-gray-500">{l.available_expiry_qty ?? '—'}</Td>
                  <Td className="tabular-nums text-gray-500">{l.available_qty ?? '—'}</Td>
                  <Td className="tabular-nums text-gray-500">{l.item_expiry || '—'}</Td>
                  <Td className="text-gray-500">{l.batchno || '—'}</Td>
                  {/* ── العبوة = the item's UNIT (علبة/شريط), display-only (NOT a bonus) ── */}
                  <Td className="text-gray-600">{l.unit_name || 'علبة'}</Td>

                  {/* ── الكمية Q + units (Q) entry ── */}
                  <td className="px-1 py-1.5 text-center">
                    <div className="flex items-center justify-center gap-0.5">
                      {/* Enter on qty → discount (or back to search when the discount is locked) */}
                      <input type="number" step="any" value={l.qty} data-pos-cell={`qty-${i}`} title={STEP_HINT}
                             onClick={e => e.stopPropagation()}
                             {...numFieldHandlers({ P, i, k: 'qty', step: 1, onEnter: () => focusPosCell(P.discountLocked ? 'search' : `cust_discp-${i}`) })}
                             onChange={e => P.setLine(i, 'qty', e.target.value)}
                             className="pos-num w-16 border rounded px-1 py-0.5 text-center font-semibold tabular-nums" />
                      {onOpenUnits && l.pack_qty > 1 && (
                        <button onClick={e => { e.stopPropagation(); onOpenUnits(i) }}
                                title={`إدخال بالوحدات/الشرائط — العبوة ${l.pack_qty} (Q)`}
                                className="text-[10px] border rounded px-1 py-0.5 text-gray-500 hover:bg-gray-100 leading-none">Q</button>
                      )}
                    </div>
                  </td>

                  {/* ── Unit Price = per-unit reference (unitsaleprice), display-only ── */}
                  <Td className="tabular-nums text-gray-500">{money(l.unit_price)}</Td>
                  {/* ── Pkg Price = the per-pack price that drives الإجمالي (item_sale_price) ── */}
                  <TdInp l={l} i={i} k="item_sale_price" P={P} />
                  {/* ── ض.ق % (editable) ── */}
                  <TdInp l={l} i={i} k="sale_tax_pct" P={P} />

                  {/* ── خصم %: retrieved + manager-locked for contract/permanent (server-enforced too) ── */}
                  <td className="px-1 py-1.5 text-center">
                    <div className="relative inline-block">
                      <input type="number" step="any" value={l.cust_discp} onClick={e => e.stopPropagation()}
                             data-pos-cell={`cust_discp-${i}`}
                             {...numFieldHandlers({ P, i, k: 'cust_discp', step: 1, onEnter: () => focusPosCell(P.discountLocked ? 'search' : `sell_price-${i}`) })}
                             readOnly={P.discountLocked} title={P.discountLocked ? '🔒 خصم التعاقد/الدائم — يتطلب صلاحية مدير' : STEP_HINT}
                             onChange={e => P.setLine(i, 'cust_discp', e.target.value)}
                             className={`pos-num w-14 border rounded px-1 py-0.5 text-center tabular-nums ${P.discountLocked ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : discOn ? 'border-amber-300 bg-amber-50 text-amber-800 font-semibold' : ''}`} />
                      {P.discountLocked && <span className="absolute -top-2 -left-2 text-[10px]" title="يتطلب صلاحية مدير">🔒</span>}
                    </div>
                    {!P.discountLocked && P.suggest.map[l.softech_itemcode] != null && (
                      <button onClick={e => { e.stopPropagation(); P.applySuggested(i) }}
                              title="تطبيق الخصم المقترح" className="text-[9px] text-emerald-700 block w-full mt-0.5 hover:underline">مقترح {P.suggest.map[l.softech_itemcode]}%</button>
                    )}
                    {/* per-item discount ceiling = items.posdiscp (max discount), manager-visible */}
                    {P.ref?.can_see_discount_cap && P.suggest.caps?.[l.softech_itemcode] != null && (
                      <span title="الحد الأقصى للخصم لهذا الصنف (items.posdiscp)" className="text-[9px] text-gray-400 block w-full text-center">≤ {P.suggest.caps[l.softech_itemcode]}%</span>
                    )}
                  </td>

                  {/* ── مبلغ الخصم (discount VALUE) — bidirectional with خصم% and سعر العبوة (all → cust_discp) ── */}
                  <td className="px-1 py-1.5 text-center">
                    <input type="number" step="any" value={P.lineDiscValue(l)} onClick={e => e.stopPropagation()}
                           readOnly={P.discountLocked} title={P.discountLocked ? '🔒 خصم التعاقد — يتطلب صلاحية مدير' : 'مبلغ الخصم — يُحسب منه خصم % وسعر البيع'}
                           onChange={e => P.setLine(i, 'disc_value', e.target.value)}
                           className={`pos-num w-16 border rounded px-1 py-0.5 text-center tabular-nums ${P.discountLocked ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : discOn ? 'border-amber-300 bg-amber-50 text-amber-800' : ''}`} />
                  </td>
                  {/* ── م.ض.ق.م (tax amount, display) ── */}
                  <Td className="tabular-nums text-gray-500">{money(taxAmt)}</Td>
                  {/* ── سعر العبوة = intended NET sell price per pack — editable, bidirectional (100 list → type 90 = 10% off) ── */}
                  <td className="px-1 py-1.5 text-center">
                    <input type="number" step="any" value={P.lineSellPrice(l)} onClick={e => e.stopPropagation()}
                           readOnly={P.discountLocked} data-pos-cell={`sell_price-${i}`}
                           title={P.discountLocked ? '🔒 خصم التعاقد — يتطلب صلاحية مدير' : 'سعر البيع المقصود للعبوة — يُحسب منه الخصم'}
                           {...numFieldHandlers({ P, i, k: 'cust_discp', step: 1, onEnter: () => focusPosCell('search') })}
                           onChange={e => P.setLine(i, 'sell_price', e.target.value)}
                           className={`pos-num w-20 border rounded px-1 py-0.5 text-center tabular-nums ${P.discountLocked ? 'bg-gray-100 text-gray-500 cursor-not-allowed' : ''}`} />
                  </td>
                  <Td className="font-bold tabular-nums text-gray-900">{money(net)}</Td>

                  {/* ── delete ── */}
                  <td className="px-1 py-1.5 text-center">
                    <button onClick={e => { e.stopPropagation(); P.removeLine(i) }}
                            title="حذف الصنف (F4)" className="text-red-400 hover:text-red-600 text-sm">✕</button>
                  </td>
                </tr>
              )
            })}
            {!P.lines.length && <tr><td colSpan={COLS.length} className="text-center text-gray-400 py-10">ابحث عن صنف لإضافته (Item Search)</td></tr>}
          </tbody>
        </table>
      </div>

      {/* ── collapsible intelligence footer — bounded height so it never steals grid space ── */}
      {(P.lines.length > 0 || custId) && (
        <div className="shrink-0 border-t bg-gray-50/60 px-2">
          <button onClick={toggleIntel} className="w-full text-right text-[11px] text-gray-500 hover:text-gray-700 py-1 flex items-center justify-between">
            <span>💡 اقتراحات وعروض (تاريخ العميل · FBT · عروض)</span><span>{intelOpen ? '▾' : '▸'}</span>
          </button>
          {intelOpen && (
            <div className="max-h-[34vh] overflow-auto pb-2">
              {/* PIC's own recent purchases → one-tap suggestions (revalidated, read-only) */}
              <PicSuggestions P={P} />
              {/* Applicable offers (READ-ONLY preview — not auto-applied to the invoice) */}
              <OffersPanel P={P} />
              {/* Ranked, safety-filtered basket opportunities (FBT + personal + bundle) */}
              <BasketIntelPanel
                itemCodes={P.lines.map(l => l.softech_itemcode).filter(Boolean)}
                customerId={P.customer?.id}
                branchId={P.branch}
                onAdd={P.addItem}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* (OffersPanel extracted to components/OffersPanel.jsx — shared web + mobile.) */

/* ───────────────────────── Payment tab ───────────────────────── */
function PaymentTab({ P }) {
  // Indirect-POS collects نقدى / آجل only. Card & cheque details are entered on the cashier
  // screen after this order is sent — not duplicated here.
  const cols = ['التاريخ', 'طريقة السداد', 'المبلغ بالعملة', 'العملة', 'سعر التحويل', 'المبلغ المحلى', 'مسلسل داخلى', '']
  const change = Number(P.totals.change || 0)
  return (
    <div className="p-2">
      <div className="flex items-center gap-3 flex-wrap text-xs mb-2">
        <span className="flex items-center gap-1.5 text-white rounded-lg px-3 py-1" style={{ background: '#022871' }}>الصافي <b className="text-base tabular-nums">{money(P.totals.net)}</b></span>
        <span className="text-gray-500">المدفوع <b className="text-gray-800 tabular-nums">{money(P.totals.paid)}</b></span>
        {change < -0.005
          ? <span className="text-red-600 font-medium">متبقٍّ <b className="tabular-nums">{money(-change)}</b></span>
          : <span className="text-emerald-700 font-medium">الفكة <b className="tabular-nums">{money(change)}</b></span>}
        <span className="flex-1" />
        <button onClick={() => { const r = Number(P.tenders[0]?.exchange_rate || 1) || 1; P.setTender(0, 'amount', +(Number(P.totals.net) / r).toFixed(2)) }}
                title="اجعل المدفوع = الصافي (أول طريقة سداد)" className="text-[11px] px-2 py-1 rounded border bg-white hover:bg-gray-50">⚖ وازن مع الصافي</button>
      </div>
      <div className="text-[11px] text-gray-400 mb-2">💳 تُجمَّع نقدى / آجل فقط — تفاصيل البطاقة/الشيك تُدخل على شاشة الكاشير بعد الإرسال.</div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border">
          <thead className="text-white" style={{ background: '#022871' }}><tr>{cols.map((c, i) => <th key={i} className="px-1.5 py-1.5 whitespace-nowrap font-medium text-[11px]">{c}</th>)}</tr></thead>
          <tbody>
            {P.tenders.map((t, i) => (
              <tr key={i} className="border-b">
                <Td>{P.docDate}</Td>
                <Td><select value={t.pay_type} onChange={e => P.setTender(i, 'pay_type', e.target.value)} className="inp">{PAY_METHODS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}</select></Td>
                <PInp t={t} i={i} k="amount" P={P} step="0.01" />
                <Td><input value={t.currency} onChange={e => P.setTender(i, 'currency', e.target.value)} className="inp w-16" /></Td>
                <PInp t={t} i={i} k="exchange_rate" P={P} step="0.0001" />
                <Td className="tabular-nums font-semibold">{money(Number(t.amount || 0) * Number(t.exchange_rate || 1))}</Td>
                <Td><input value={t.internal_payserial} onChange={e => P.setTender(i, 'internal_payserial', e.target.value)} className="inp w-20" /></Td>
                <Td>{P.tenders.length > 1 && <button onClick={() => P.removeTender(i)} title="حذف طريقة السداد" className="text-red-400 hover:text-red-600">✕</button>}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button onClick={P.addTender} className="mt-2 text-xs px-2.5 py-1 rounded border border-dashed border-gray-300 text-gray-600 hover:bg-gray-50">+ طريقة سداد</button>
    </div>
  )
}

/* ─────────────────── Contract Emp. Data tab ─────────────────── */
// Fields are per-contract: P.empDataFields is the live spec (which fields show + custom labels, from
// SOFTECH motalba_fields), falling back to the 12 standard titles when no contract is selected yet.
function ContractTab({ P }) {
  const C = (k, v) => P.setClaim({ ...P.claim, [k]: v })
  if (!P.isClaim) return <div className="p-6 text-gray-400 text-sm">📋 تظهر بيانات المريض/المطالبة لقنوات التعاقد والتأمين فقط.</div>
  const fields = P.empDataFields || CONTRACT_EMP_FIELDS
  return (
    <div className="p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-bold" style={{ color: '#022871' }}>📋 بيانات التعاقد / المطالبة</span>
        {P.contractFields != null && (
          <span className="text-[11px] text-gray-500">
            — الحقول محددة حسب التعاقد ({fields.length} حقل){fields.length === 0 ? ' · لا توجد حقول مطلوبة' : ''}
          </span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-3 max-w-3xl">
        {fields.map(({ key, label, type }) => (
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
function FooterBar({ P, onParked, onReceipt }) {
  const paid = Number(P.totals.paid || 0)
  const change = Number(P.totals.change || 0)   // ≥0 → فكة (over-paid); <0 → متبقٍّ (still due)
  return (
    <div className="border-t bg-white px-3 py-1.5 flex items-center gap-2.5 text-xs shadow-[0_-1px_3px_rgba(0,0,0,0.04)] flex-wrap">
      <span className="text-gray-500">الإجمالي <b className="text-gray-800 tabular-nums">{money(P.totals.gross)}</b></span>
      <span className="text-orange-600">− الخصم <b className="tabular-nums">{money(P.totals.discount)}</b></span>
      <span className="text-gray-500">ض.ق.م <b className="text-gray-800 tabular-nums">{money(P.totals.tax)}</b></span>
      <span className="flex items-center gap-1.5 text-white rounded-lg px-3 py-1" style={{ background: '#022871' }}>
        الصافي <b className="text-base tabular-nums">{money(P.totals.net)}</b>
      </span>
      {paid > 0 && <span className="text-gray-500">المدفوع <b className="text-gray-800 tabular-nums">{money(paid)}</b></span>}
      {paid > 0 && (change < -0.005
        ? <span className="text-red-600 font-medium">متبقٍّ <b className="tabular-nums">{money(-change)}</b></span>
        : <span className="text-emerald-700 font-medium">الفكة <b className="tabular-nums">{money(change)}</b></span>)}
      <PointsBadge P={P} />
      <span className="text-gray-400 tabular-nums">🧾 {P.lines.length}</span>
      <div className="flex-1 min-w-2" />
      {/* finalize actions — always visible so the side panels can collapse away */}
      <button onClick={P.parkOrder} title="تعليق السلة" className="h-8 px-2 rounded border bg-white hover:bg-gray-50">⏸</button>
      <button onClick={onParked} title="السلال المعلّقة" className="h-8 px-2 rounded border bg-white hover:bg-gray-50">📥{P.parked.length ? ` ${P.parked.length}` : ''}</button>
      <button onClick={onReceipt} disabled={!P.lines.length} title="معاينة الإيصال" className="h-8 px-2 rounded border bg-white hover:bg-gray-50 disabled:opacity-40">🧾</button>
      <button onClick={() => P.submit(false)} disabled={P.busy || !P.lines.length} title="معاينة الإرسال (تجريبى)"
              className="h-8 px-3 rounded text-white font-semibold disabled:opacity-40 flex items-center gap-1.5" style={{ background: '#022871' }}>
        {P.busy ? '...' : <>🧾 معاينة <kbd className="text-[10px] bg-white/20 rounded px-1">F9</kbd></>}
      </button>
      {P.ref?.writer_enabled
        ? <button onClick={() => P.submit(true)} disabled={P.busy || !P.lines.length} title="إرسال فعلي للكاشير"
                  className="h-8 px-3 rounded bg-red-600 text-white font-semibold disabled:opacity-40 flex items-center gap-1.5">⚠ إرسال <kbd className="text-[10px] bg-white/20 rounded px-1">F10</kbd></button>
        : <span className="h-8 px-2 rounded bg-gray-100 text-gray-400 text-[11px] flex items-center" title="يُفعّل بمفتاح الكاتب المعتمد من المالك">🔒 مُعطّل</span>}
      <button onClick={P.reset} title="أمر جديد" className="h-8 px-2 rounded border text-red-600 hover:bg-red-50">↺</button>
    </div>
  )
}

// Errors / status message / SOFTECH queue — pulled out of the (collapsible) numpad so it stays
// visible in the center column no matter which side panels are open.
function StatusBar({ P }) {
  const q = P.queueStatus || {}
  const hasQueue = (q.queued || 0) + (q.push_failed || 0) + (q.pushing || 0) > 0
  if (!P.errs.length && !P.msg && !hasQueue) return null
  // §7 "one question at a time": surface the FIRST blocker as an actionable ErrorState with a jump-to-fix;
  // the rest are counted and appear in turn as each is resolved. Tolerant of string OR {text,tab} errors.
  const errs = P.errs.map(e => (typeof e === 'string' ? { text: e, tab: null } : e))
  const first = errs[0]
  const jumpable = first && ['items', 'payment', 'contract'].includes(first.tab)
  return (
    <div className="border-t bg-gray-50 px-3 py-1.5 flex items-center gap-2 text-[11px]">
      {first && (
        <div className="flex-1 min-w-0">
          <ErrorState tone="warn" title={first.text}
            detail={errs.length > 1 ? `+ ${errs.length - 1} تنبيه آخر — يظهر تِباعاً بعد المعالجة` : undefined}
            actionLabel={jumpable ? 'إصلاح ←' : undefined}
            onAction={jumpable ? () => P.setActiveTab(first.tab) : undefined} />
        </div>
      )}
      {!first && P.msg && <div className="bg-blue-50 text-blue-800 rounded px-2 py-1 flex-1 truncate" title={P.msg}>{P.msg}</div>}
      {hasQueue && <div className="shrink-0 min-w-[12rem]"><QueueIndicator P={P} /></div>}
    </div>
  )
}

/* SOFTECH loyalty-points indicator — points are awarded per-item by SOFTECH at the cashier's
 * finalization (not reproducible read-only), so we surface enrollment status, not a figure. */
function PointsBadge({ P }) {
  const pic = P.picCustomer?.softech_pic || P.customer?.softech_pic
  if (!P.pointsInfo.eligible) return <span className="text-gray-400" title="هذه القناة لا تكتسب نقاطاً">🎁 لا نقاط لهذه القناة</span>
  if (!pic) return <span className="text-gray-400">🎁 اختر عميلاً لاكتساب النقاط</span>
  if (!P.pointsInfo.enrolled) return <span className="text-amber-600" title="العميل غير مسجّل بنظام النقاط في SOFTECH">🎁 غير مسجّل بنظام النقاط</span>
  return <span className="text-emerald-700" title="تُحتسب تلقائياً عند إنهاء الكاشير حسب أصناف الفاتورة">🎁 مسجّل — نقاط عند الإنهاء</span>
}

/* Keyboard cheat-sheet — makes the wired SOFTECH-parity speed keys discoverable so cashiers
 * actually use them (biggest time-to-finalize win). Collapsible, remembered per-device. */
const POS_SHORTCUTS = [
  ['F2', 'إضافة صنف (بحث)'],
  ['⏎', 'كمية ← خصم ← بحث'],
  ['F4 / Del', 'حذف الصنف المحدد'],
  ['Q', 'إدخال الكمية بالوحدات/الشرائط'],
  ['Shift+↑/↓', 'زيادة/إنقاص قيمة الحقل (كمية ±1 · نسبة ±1 · سعر ±1)'],
  ['↑ ↓', 'تنقّل بين الأصناف'],
  ['Ctrl+F2/3', 'نقدى / توصيل'],
  ['Ctrl+F1', 'بحث متقدم'],
  ['Ctrl+K', 'بحث شامل'],
  ['F9', 'معاينة الإرسال'],
  ['F10', 'إرسال فعلي (عند التفعيل)'],
]
function KeyboardLegend() {
  const [open, setOpen] = useState(() => { try { return localStorage.getItem('pos_shortcuts_open') === '1' } catch { return false } })
  const toggle = () => setOpen(o => { const n = !o; try { localStorage.setItem('pos_shortcuts_open', n ? '1' : '0') } catch { /* private mode */ } return n })
  return (
    <div className="border-t mt-2 pt-2 text-right">
      <button onClick={toggle} className="w-full flex items-center justify-between text-[11px] text-gray-500 hover:text-gray-700">
        <span>⌨ اختصارات لوحة المفاتيح</span><span>{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="mt-1.5 space-y-1">
          {POS_SHORTCUTS.map(([k, d]) => (
            <div key={k} className="flex items-center justify-between gap-2 text-[10px]">
              <span className="text-gray-500 truncate">{d}</span>
              <kbd className="shrink-0 bg-white border rounded px-1 py-0.5 font-mono text-gray-700">{k}</kbd>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// On-screen calculator only — the finalize actions + status now live in the footer, so this
// whole column can be collapsed away (a keyboard cashier types straight into the cells).
function NumpadColumn({ P, onCollapse }) {
  return (
    <div className="w-48 bg-gray-50 border-r p-2 flex flex-col gap-2 overflow-auto">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-gray-500">لوحة الأرقام</span>
        <button onClick={onCollapse} title="طيّ اللوحة لتوسيع الأصناف" className="text-gray-400 hover:text-gray-700 text-sm">‹</button>
      </div>
      <div className="grid grid-cols-3 gap-1">
        {[['qty', '🔢 كمية'], ['disc', '٪ خصم'], ['price', '💲 سعر']].map(([m, l]) => (
          <button key={m} onClick={() => P.setNumMode(m)} title={`لوحة الأرقام تعدّل ${l}`}
                  className={`py-1.5 rounded text-xs ${P.numMode === m ? 'text-white' : 'bg-white border'}`}
                  style={P.numMode === m ? { background: '#022871' } : undefined}>{l}</button>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-1">
        {NUMKEYS.map(k => <button key={k} onClick={() => P.numpad(k)} className="py-2.5 rounded bg-white border font-semibold hover:bg-gray-100">{k}</button>)}
        <button onClick={() => P.numpad('back')} className="py-2.5 rounded bg-white border col-span-2">⌫</button>
        <button onClick={() => P.numpad('C')} className="py-2.5 rounded bg-red-50 border border-red-200 text-red-600">C</button>
      </div>
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
// Number cells must NOT change on a stray arrow-key or scroll (that caused wrong data entry). You
// have to HOLD SHIFT to step, and each field steps by a whole, sensible amount (qty 1 pack · % 1 ·
// price 1). Plain wheel just blurs so the grid scrolls; plain arrows do nothing. Reads the LIVE DOM
// value so a held Shift+Arrow keeps stepping. `onEnter` (qty/discount) still runs on Enter.
export function numFieldHandlers({ P, i, k, step = 1, onEnter }) {
  const bump = (el, dir) => P.setLine(i, k, Math.max(0, +((Number(el.value) || 0) + dir * step).toFixed(5)))
  return {
    onKeyDown: e => {
      if (e.key === 'Enter') { if (onEnter) { e.preventDefault(); onEnter() } return }
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault()                                          // never nudge on a plain arrow
        if (e.shiftKey) bump(e.currentTarget, e.key === 'ArrowUp' ? 1 : -1)  // Shift+Arrow = intentional step
      }
    },
    onWheel: e => {
      if (e.shiftKey) { e.preventDefault(); bump(e.currentTarget, e.deltaY < 0 ? 1 : -1) }
      else e.currentTarget.blur()                                  // plain wheel → let the page scroll
    },
  }
}
export const STEP_HINT = 'Shift + ↑/↓ أو Shift + عجلة الماوس للزيادة/الإنقاص'
// compact editable numeric cell (price / tax) — no keyboard target (only qty + discount have those)
function TdInp({ l, i, k, P, step = 1 }) {
  return <Td><input type="number" step="any" value={l[k]} onClick={e => e.stopPropagation()} title={STEP_HINT}
    onChange={e => P.setLine(i, k, e.target.value)} {...numFieldHandlers({ P, i, k, step })}
    className="pos-num w-16 border rounded px-1 py-0.5 text-center tabular-nums" /></Td>
}
// Move keyboard focus to another grid cell, a header flow field, or the item search — the SOFTECH rapid
// path. Targets: 'search', 'flow:<key>' (a header field with data-pos-flow), or a data-pos-cell key.
function focusPosCell(target) {
  setTimeout(() => {
    const sel = target === 'search' ? '#pos-item-search input'
      : (typeof target === 'string' && target.startsWith('flow:')) ? `[data-pos-flow="${target.slice(5)}"]`
      : `[data-pos-cell="${target}"]`
    const el = document.querySelector(sel)
    if (el) { el.focus(); el.select?.() }
  }, 0)
}
// Header tab-flow: Enter / Tab → next field, Shift+Enter / Shift+Tab → previous. A single LOGICAL order
// (نوع العميل → إسم العميل → PIC → المخزن → ملاحظات → الأصناف → الطابعة) that matches SOFTECH but is
// reordered for a sane cascade. `next`/`prev` are focusPosCell targets.
export function posFlow(next, prev, tabOnly = false) {
  return {
    onKeyDown: (e) => {
      const fwd = (e.key === 'Tab' && !e.shiftKey) || (!tabOnly && e.key === 'Enter')  // name field: Enter picks
      const back = e.key === 'Tab' && e.shiftKey
      if (fwd) { if (next) { e.preventDefault(); focusPosCell(next) } }
      else if (back) { if (prev) { e.preventDefault(); focusPosCell(prev) } }
    },
  }
}
function PInp({ t, i, k, P, step }) {
  return <Td><input type="number" step={step} value={t[k]} onChange={e => P.setTender(i, k, e.target.value)} className="w-24 border rounded px-1 text-center" /></Td>
}

function CouponModal({ P }) {
  const m = P.couponModal
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => P.setCouponModal(null)}>
      <div dir="rtl" className="bg-white rounded-lg p-4 w-[28rem]" onClick={e => e.stopPropagation()}>
        <div className="font-bold mb-1">كوبون هدية — {m.item.name}</div>
        <div className="text-xs text-gray-500 mb-3">
          أدخل السريال المطبوع على الكوبون (مثال 27301-ABC123). يجب أن تكون الفاتورة على كود صاحب الكوبون.
        </div>
        <input autoFocus dir="ltr" value={m.serial} placeholder="27301-ABC123"
               onChange={e => P.setCouponModal(x => ({ ...x, serial: e.target.value.toUpperCase(), errors: [] }))}
               onKeyDown={e => { if (e.key === 'Enter') P.checkCoupon(); if (e.key === 'Escape') P.setCouponModal(null) }}
               className="w-full border rounded px-2 py-2 font-mono text-lg text-center tracking-wider" />
        {m.errors?.length > 0 && (
          <ul className="mt-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2 list-disc pr-5">
            {m.errors.map((er, i) => <li key={i}>{er}</li>)}
          </ul>
        )}
        <div className="flex justify-end gap-2 mt-3">
          <button onClick={() => P.setCouponModal(null)} className="px-4 py-1.5 rounded border">إلغاء (Esc)</button>
          <button onClick={P.checkCoupon} disabled={m.checking}
                  className={`px-4 py-1.5 rounded text-white ${m.checking ? 'bg-gray-300' : 'bg-blue-600'}`}>
            {m.checking ? 'جارٍ التحقق…' : 'تحقق وأضف'}
          </button>
        </div>
      </div>
    </div>
  )
}

function BatchModal({ P }) {
  const m = P.batchModal
  const pickedQty = m.picks.reduce((s, p) => s + (Number(p) || 0), 0)
  const blocked = m.mandatory && pickedQty <= 0   // mandatory-batch item needs a real pick
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => P.setBatchModal(null)}>
      <div dir="rtl" className="bg-white rounded-lg p-4 w-[36rem] max-h-[85vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="font-bold mb-1 flex items-center gap-2">
          Item Code: {m.item.softech_id} — WareHouse: {P.storeCode || '—'}
          {m.mandatory && <BatchBadge label="إلزامى" />}
        </div>
        <div className="text-xs text-gray-500 mb-2">{m.item.name} — اختر من تشغيلة أو وزّع على أكثر من صلاحية.</div>
        {m.mandatory && (
          <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1 mb-3">
            هذا الصنف «رقم القطعة أو الباتش» — اختيار التشغيلة إلزامى قبل الإضافة.
          </div>
        )}
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
          <button onClick={P.confirmBatchPick} disabled={blocked}
                  title={blocked ? 'اختر التشغيلة أولاً' : ''}
                  className={`px-4 py-1.5 rounded text-white ${blocked ? 'bg-gray-300 cursor-not-allowed' : 'bg-blue-600'}`}>إضافة</button>
        </div>
      </div>
    </div>
  )
}
