/**
 * WorkflowPanel — live بدل case actions (doc 25 Phase 1), shown inside the case workspace.
 *
 * Shows only what the case state allows: calculate → submit → approve/reject → legs (purchase,
 * contract sale, product sales) → post. `c.workflow.can` only HIDES buttons; the API re-checks
 * every action (role + employee grant + maker-checker + branch). Every call sends c.version, so a
 * stale screen gets a clear 409 instead of overwriting someone else's change. No modals.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { replacementApi } from '../../api/client'
import ItemSearchInput from '../../components/ItemSearchInput'
import { Chip, errText, money } from '../supply/supplyUi'

const OP_TONE = { planned: 'gray', dry_run: 'amber', posting: 'blue', posted: 'indigo', posted_verified: 'emerald',
                  failed: 'rose', cancelled: 'gray' }

function Box({ title, children, tone = 'border-gray-200' }) {
  return (
    <div className={`bg-white border ${tone} rounded-xl p-4 space-y-3`}>
      {title && <div className="text-sm font-semibold text-gray-800">{title}</div>}
      {children}
    </div>
  )
}

function Btn({ children, onClick, disabled, kind = 'primary' }) {
  const cls = kind === 'primary' ? 'bg-blue-600 text-white' : kind === 'danger' ? 'border border-rose-300 text-rose-700'
    : kind === 'ok' ? 'bg-emerald-600 text-white' : 'border border-gray-300 text-gray-700'
  return <button type="button" disabled={disabled} onClick={onClick}
                 className={`text-sm px-3 py-1.5 rounded-lg disabled:opacity-40 ${cls}`}>{children}</button>
}

// Parallel entry: a document the staff already posted natively in SOFTECH (branch / number / date).
function NativeDocLink({ label, branchcode, busy, onLink }) {
  const [d, setD] = useState({ branchcode, docnumber: '', docdate: '' })
  return (
    <div className="flex gap-2 flex-wrap items-center">
      <span className="text-xs text-gray-500">{label}</span>
      <input value={d.branchcode} onChange={(e) => setD({ ...d, branchcode: e.target.value })} className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-16" />
      <input value={d.docnumber} onChange={(e) => setD({ ...d, docnumber: e.target.value })} placeholder="رقم المستند" className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-32 font-mono" />
      <input type="date" value={d.docdate} onChange={(e) => setD({ ...d, docdate: e.target.value })} className="border border-gray-300 rounded-lg px-2 py-1 text-sm" />
      <Btn kind="ghost" disabled={busy || !d.docnumber || !d.docdate} onClick={() => onLink(d)}>ربط</Btn>
    </div>
  )
}

const nativeStatus = (o) => (o.kind === 'purchase' ? 'بانتظار ظهورها في المرآة' : 'بانتظار سند الكاشير')

export default function WorkflowPanel({ c }) {
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')
  const [ov, setOv] = useState({ pct: '', reason: '' })
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [link, setLink] = useState({ branchcode: c.branchcode, docnumber: '', docdate: '' })
  const [channel, setChannel] = useState('cash')
  const [basket, setBasket] = useState([])
  const wf = c.workflow || {}
  const can = wf.can || {}
  const v = { version: c.version }

  const m = useMutation({
    mutationFn: ({ fn, args }) => fn(...args),
    onSuccess: (r) => { qc.setQueryData(['replacement-case', String(c.id)], r.data); setMsg(''); setBasket([]) },
    onError: (e) => setMsg(errText(e) + (e?.response?.status === 409 ? ' ⟳' : '')),
  })
  const run = (fn, ...args) => m.mutate({ fn, args })
  const busy = m.isPending
  const ops = c.operations || []
  const opOf = (kind) => ops.filter((o) => o.kind === kind && o.status !== 'cancelled')
  const hasContract = (c.documents || []).some((d) => d.role === 'contract_sale' && d.status === 'confirmed')
  const executing = ['approved', 'executing', 'entitlement_active', 'settled'].includes(c.status)
  const editable = ['draft', 'calculated'].includes(c.status) && !wf.locked
  const calc = c.current_calc

  if (!wf.live) return null
  return (
    <div className="space-y-3">
      {!wf.posting_enabled && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-xs rounded-lg px-3 py-2">
          وضع تجريبي: الترحيل إلى SOFTECH متوقف — زر «ترحيل» يعرض خطة المستند فقط ولا يكتب أي شيء.
        </div>
      )}
      {msg && <div className="bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-lg px-3 py-2">{msg}</div>}

      {/* ── calculation ─────────────────────────────────────────────── */}
      <Box title="حساب الرصيد (يحسبه السيرفر)">
        {calc ? (
          <>
            <div className="text-xs text-gray-500">القاعدة: {calc.rule_label} · خصم القاعدة {calc.rule_deduction_pct}% · المطبق {calc.applied_deduction_pct}%
              {calc.override_reason && <> · سبب التعديل: «{calc.override_reason}»</>}</div>
            <table className="w-full text-sm">
              <thead className="text-[11px] text-gray-500 bg-gray-50"><tr>
                {['الصنف', 'الكمية', 'سعر الجمهور', 'قيمة الجمهور', 'الخصم', 'صافي الوحدة', 'الرصيد'].map((h) => <th key={h} className="px-2 py-1 text-right">{h}</th>)}
              </tr></thead>
              <tbody>
                {calc.lines.map((l) => (
                  <tr key={l.itemcode} className="border-t border-gray-100">
                    <td className="px-2 py-1">{l.name || l.itemcode}</td>
                    <td className="px-2 py-1 tabular-nums">{Number(l.qty)}</td>
                    <td className="px-2 py-1 tabular-nums">{money(l.public_price)}</td>
                    <td className="px-2 py-1 tabular-nums">{money(l.eligible)}</td>
                    <td className="px-2 py-1 tabular-nums">{Number(l.deduction_pct)}%</td>
                    <td className="px-2 py-1 tabular-nums">{l.unit_net}</td>
                    <td className="px-2 py-1 tabular-nums font-semibold">{money(l.entitlement)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex gap-2 flex-wrap text-xs">
              <Chip tone="gray">قيمة الجمهور {money(calc.public_value)}</Chip>
              {Number(calc.rounding_adj) !== 0 && <Chip tone="gray">تقريب {money(calc.rounding_adj)}</Chip>}
              <Chip tone="emerald">الرصيد {money(calc.entitlement)}</Chip>
            </div>
          </>
        ) : <div className="text-sm text-gray-400">لم يُحسب بعد.</div>}
        {editable && can.create && (
          <div className="flex gap-2 items-center flex-wrap">
            <input value={ov.pct} onChange={(e) => setOv({ ...ov, pct: e.target.value })} placeholder="نسبة خصم مختلفة (اختياري)"
                   className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-48" />
            {ov.pct !== '' && <input value={ov.reason} onChange={(e) => setOv({ ...ov, reason: e.target.value })} placeholder="سبب التعديل (إلزامي)"
                                     className="border border-gray-300 rounded-lg px-2 py-1 text-sm flex-1" />}
            <Btn disabled={busy} onClick={() => run(replacementApi.calculate, c.id,
              { ...v, ...(ov.pct !== '' ? { override_pct: ov.pct, override_reason: ov.reason } : {}) })}>احسب</Btn>
          </div>
        )}
        {c.status === 'calculated' && can.create && (
          <div className="flex gap-2 items-center flex-wrap">
            <Btn kind="ok" disabled={busy} onClick={() => run(replacementApi.submit, c.id, v)}>
              {wf.route_preview?.workflow ? 'إرسال للاعتماد' : 'اعتماد تلقائي (ضمن الحدود)'}
            </Btn>
            {(wf.route_preview?.reasons || []).map((r) => <Chip key={r} tone="amber">{r}</Chip>)}
          </div>
        )}
      </Box>

      {/* ── approval ────────────────────────────────────────────────── */}
      {c.status === 'awaiting_approval' && (
        <Box title="الاعتماد" tone="border-amber-200">
          <div className="text-sm">{wf.approval?.workflow} · الخطوة {wf.approval?.step}</div>
          <div className="flex gap-1 flex-wrap">{(wf.approval?.reasons || []).map((r) => <Chip key={r} tone="amber">{r}</Chip>)}</div>
          {can.approve ? (
            <div className="flex gap-2 items-center">
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="ملاحظة (إلزامية عند الرفض)"
                     className="border border-gray-300 rounded-lg px-2 py-1 text-sm flex-1" />
              <Btn kind="ok" disabled={busy} onClick={() => run(replacementApi.approve, c.id, { ...v, note })}>اعتماد</Btn>
              <Btn kind="danger" disabled={busy || !note.trim()} onClick={() => run(replacementApi.reject, c.id, { ...v, note })}>رفض</Btn>
            </div>
          ) : <div className="text-xs text-gray-500">بانتظار المعتمد المختص (لا يمكن لمنشئ الحالة اعتمادها).</div>}
        </Box>
      )}

      {/* ── execution legs ──────────────────────────────────────────── */}
      {executing && (
        <Box title="تنفيذ المستندات">
          {/* purchase */}
          <div className="space-y-1">
            <div className="text-xs text-gray-500">١ — فاتورة الشراء من المورد الافتراضي (تُنشئ الرصيد)</div>
            {!opOf('purchase').length && can.post &&
              <Btn disabled={busy} onClick={() => run(replacementApi.preparePurchase, c.id, v)}>تجهيز فاتورة الشراء</Btn>}
            {!opOf('purchase').some((o) => !o.result?.native || o.status === 'posted_verified') && can.create &&
              <NativeDocLink label="أو اربط فاتورة الشراء المُدخلة في SOFTECH:" branchcode={c.branchcode} busy={busy}
                             onLink={(d) => run(replacementApi.linkPurchase, c.id, { ...v, ...d })} />}
          </div>
          {/* contract */}
          {c.source_type === 'insurance_rx' && !hasContract && (
            <div className="space-y-1">
              <div className="text-xs text-gray-500">٢ — فاتورة التعاقد: اربط الفاتورة التي صُرفت بالفعل، أو جهّز بيع تعاقد للكاشير</div>
              <div className="flex gap-2 flex-wrap items-center">
                <input value={link.branchcode} onChange={(e) => setLink({ ...link, branchcode: e.target.value })} className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-16" />
                <input value={link.docnumber} onChange={(e) => setLink({ ...link, docnumber: e.target.value })} placeholder="رقم الفاتورة" className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-32 font-mono" />
                <input type="date" value={link.docdate} onChange={(e) => setLink({ ...link, docdate: e.target.value })} className="border border-gray-300 rounded-lg px-2 py-1 text-sm" />
                <Btn kind="ghost" disabled={busy || !link.docnumber || !link.docdate} onClick={() => run(replacementApi.linkContract, c.id, { ...v, ...link })}>ربط</Btn>
                {can.post && !opOf('contract_sale').length &&
                  <Btn kind="ghost" disabled={busy} onClick={() => run(replacementApi.prepareContract, c.id, v)}>تجهيز بيع تعاقد</Btn>}
              </div>
            </div>
          )}
          {/* products */}
          {c.settlement_mode !== 'cash' && can.post && (
            <div className="space-y-2">
              <div className="text-xs text-gray-500">٣ — منتجات البدل (المتاح {money(wf.available?.available)} · محجوز {money(wf.available?.reserved)})</div>
              <div className="flex gap-2 items-center flex-wrap">
                <select value={channel} onChange={(e) => setChannel(e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1 text-sm">
                  <option value="cash">نقدي (داخل الفرع)</option>
                  <option value="delivery">توصيل للمنزل</option>
                </select>
                <div className="flex-1 min-w-[240px]">
                  <ItemSearchInput placeholder="أضف منتجاً…" onSelect={(it) => it?.item_id &&
                    setBasket((b) => (b.some((x) => x.item_id === it.item_id) ? b : [...b, { item_id: it.item_id, name: it.name, price: it.pack_price, qty: 1 }]))} />
                </div>
              </div>
              {basket.map((b, i) => (
                <div key={b.item_id} className="flex items-center gap-2 text-sm">
                  <span className="flex-1">{b.name}</span>
                  <input type="number" min="0" step="any" value={b.qty}
                         onChange={(e) => setBasket((x) => x.map((y, j) => (j === i ? { ...y, qty: e.target.value } : y)))}
                         className="border border-gray-300 rounded px-2 py-0.5 w-20" />
                  <span className="tabular-nums text-gray-500 w-24">{money(b.price)}</span>
                  <button type="button" onClick={() => setBasket((x) => x.filter((_, j) => j !== i))} className="text-rose-600 text-xs">حذف</button>
                </div>
              ))}
              {!!basket.length && <Btn disabled={busy} onClick={() => run(replacementApi.prepareProducts, c.id,
                { ...v, channel, items: basket.map((b) => ({ item_id: b.item_id, qty: b.qty })) })}>تجهيز فاتورة المنتجات</Btn>}
            </div>
          )}
          {c.settlement_mode !== 'cash' && can.create && (
            <NativeDocLink label="اربط فاتورة منتجات بيعت في SOFTECH (نقدي/توصيل):" branchcode={c.branchcode} busy={busy}
                           onLink={(d) => run(replacementApi.linkProductSale, c.id, { ...v, ...d })} />
          )}
          {/* operations */}
          {!!ops.length && (
            <table className="w-full text-sm">
              <thead className="text-[11px] text-gray-500 bg-gray-50"><tr>
                {['المستند', 'القيمة', 'الحالة', 'رقم SOFTECH', ''].map((h) => <th key={h} className="px-2 py-1 text-right">{h}</th>)}
              </tr></thead>
              <tbody>
                {ops.map((o) => (
                  <tr key={o.op_id} className="border-t border-gray-100">
                    <td className="px-2 py-1">{o.kind_label}{o.target?.channel && ` · ${o.target.channel}`}
                      {o.result?.customer_topup && Number(o.result.customer_topup) > 0 && <span className="text-[11px] text-teal-700"> · يدفع المريض {money(o.result.customer_topup)}</span>}</td>
                    <td className="px-2 py-1 tabular-nums">{money(o.expected_value)}</td>
                    <td className="px-2 py-1">
                      {o.result?.native && <Chip tone="teal">يدوي في SOFTECH</Chip>}{' '}
                      <Chip tone={OP_TONE[o.status]}>{o.result?.native && o.status === 'posted' ? nativeStatus(o) : o.status_label}</Chip>
                      {o.error && <div className="text-[11px] text-rose-700">{o.error}</div>}</td>
                    <td className="px-2 py-1 font-mono text-xs">{o.result_docnumber || o.target?.softech_docnumber || '—'}</td>
                    <td className="px-2 py-1">
                      {can.post && !o.result?.native && ['planned', 'dry_run', 'failed'].includes(o.status) &&
                        <Btn disabled={busy} onClick={() => run(replacementApi.postOperation, c.id, o.op_id, v)}>
                          {wf.posting_enabled ? 'ترحيل' : 'عرض خطة الترحيل'}</Btn>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {wf.voucher_instruction && (
            <div className="bg-sky-50 border border-sky-200 rounded-lg p-3 text-sm space-y-1">
              <div className="font-semibold text-sky-900">تعليمات الكاشير — سند صرف (يدوي في SOFTECH)</div>
              <div>المورد: <b>{wf.voucher_instruction.supplier}</b> {wf.voucher_instruction.supplier_name}</div>
              <div>على فاتورة الشراء: <b className="font-mono">{wf.voucher_instruction.branch}/{wf.voucher_instruction.invoice}</b> · الرصيد {money(wf.voucher_instruction.balance)}</div>
              {Number(wf.voucher_instruction.amount_for_products) > 0 &&
                <div>قيمة سند المنتجات: <b>{money(wf.voucher_instruction.amount_for_products)}</b></div>}
              <div className="text-xs text-sky-700">ملاحظة السند: «{wf.voucher_instruction.note}» — سيُربط السند ويُراجع تلقائياً في الليلة.</div>
            </div>
          )}
        </Box>
      )}

      {/* ── reopen / cancel (before anything is posted) ─────────────── */}
      {['calculated', 'awaiting_approval', 'approved', 'draft'].includes(c.status) &&
        !ops.some((o) => ['posting', 'posted', 'posted_verified'].includes(o.status)) && (can.approve || can.create) && (
        <Box>
          <div className="flex gap-2 items-center flex-wrap">
            <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="السبب (إلزامي)"
                   className="border border-gray-300 rounded-lg px-2 py-1 text-sm flex-1" />
            {can.approve && c.status !== 'draft' &&
              <Btn kind="ghost" disabled={busy || !reason.trim()} onClick={() => run(replacementApi.reopen, c.id, { ...v, reason })}>إعادة فتح للتعديل</Btn>}
            {can.create && <Btn kind="danger" disabled={busy || !reason.trim()} onClick={() => run(replacementApi.cancel, c.id, { ...v, reason })}>إلغاء الحالة</Btn>}
          </div>
        </Box>
      )}
    </div>
  )
}
