/**
 * ReplacementCaseDetailPage — one بدل case workspace (doc 25 §12).
 *
 * Header · progress rail · lineage tree (every native document, clickable) · items ·
 * append-only ledger · exceptions · reconciliation. The only actions in Phase 0 are
 * confirming/rejecting a proposed product-receipt link and acknowledging/resolving an
 * exception — inline, no modals. Authorization is enforced by the API.
 */
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { replacementApi } from '../api/client'
import { Chip, errText, money } from './supply/supplyUi'
import { SEV_LABEL, SEV_TONE, STATUS_TONE } from './ReplacementCasesPage'
import WorkflowPanel from './replacement/WorkflowPanel'

const KIND_ICON = {
  case: '📁', prescription: '📋', item: '💊', contract_sale: '🧾', contract_return: '↩️', contract_void: '🚫',
  purchase: '📥', voucher: '💵', product_sale: '🛍️', supplier_return: '↪️', balance: '⚖️',
}
const DOC_STATUS = { confirmed: ['مؤكد', 'emerald'], proposed: ['مقترح', 'amber'], rejected: ['مرفوض', 'rose'] }

function Rail({ c }) {
  const has = (role) => c.documents.some((d) => d.role === role && d.status !== 'rejected')
  const steps = [
    ['الروشتة', c.items.length > 0],
    ['فاتورة التعاقد', has('contract_sale')],
    ['الشراء (الرصيد)', has('purchase')],
    ['الصرف', Number(c.redeemed_products) + Number(c.redeemed_cash) + Number(c.redeemed_unclassified) > 0],
    ['استهلاك الرصيد', has('purchase') && Number(c.entitlement) > 0 && Number(c.outstanding) <= 0.01],
    ['المطابقة', c.status === 'reconciled' || c.status === 'closed'],
  ]
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {steps.map(([label, ok], i) => (
        <div key={label} className="flex items-center gap-1">
          <span className={`text-xs px-2.5 py-1 rounded-full border ${ok
            ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-gray-50 border-gray-200 text-gray-400'}`}>
            {ok ? '✓' : '○'} {label}
          </span>
          {i < steps.length - 1 && <span className="text-gray-300">←</span>}
        </div>
      ))}
    </div>
  )
}

function Evidence({ items }) {
  if (!items?.length) return null
  return (
    <div className="flex gap-1 flex-wrap mt-1">
      {items.map((e, i) => (
        <span key={i} title={e.detail}
              className={`text-[10px] px-1.5 py-0.5 rounded border ${e.points > 0 ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : e.points < 0 ? 'bg-rose-50 border-rose-200 text-rose-700' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
          {e.points > 0 ? '+' : ''}{e.points} {e.detail}
        </span>
      ))}
    </div>
  )
}

function TreeNode({ node, depth, onDecide, busy }) {
  const [open, setOpen] = useState(depth < 3)
  const kids = node.children || []
  const [stLabel, stTone] = DOC_STATUS[node.status] || []
  const canDecide = node.kind === 'product_sale' && node.status === 'proposed'
  return (
    <div className={depth ? 'border-r-2 border-gray-100 pr-3 mr-2' : ''}>
      <div className="flex items-start gap-2 py-1.5">
        {kids.length ? (
          <button onClick={() => setOpen(!open)} className="text-gray-400 w-4 text-xs mt-0.5">{open ? '▾' : '◂'}</button>
        ) : <span className="w-4" />}
        <span className="text-base leading-5">{KIND_ICON[node.kind] || '•'}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-900 text-sm">{node.title}</span>
            {node.subtitle && <span className="text-xs text-gray-500 font-mono">{node.subtitle}</span>}
            {node.amount !== undefined && node.amount !== '' && (
              <span className="text-sm tabular-nums font-semibold text-gray-800">{money(node.amount)}</span>)}
            {stLabel && <Chip tone={stTone}>{stLabel}{node.origin === 'native' ? ' · SOFTECH' : ''}</Chip>}
            {node.doc?.phcode && <span className="text-[11px] text-gray-500">PIC {node.doc.phcode}</span>}
            {node.doc?.time && <span className="text-[11px] text-gray-400">⏱ {node.doc.time}</span>}
            {node.doc?.usercode && <span className="text-[11px] text-gray-400">مستخدم {node.doc.usercode}</span>}
            {node.doc?.note && <span className="text-[11px] text-gray-400 truncate max-w-[260px]" title={node.doc.note}>«{node.doc.note}»</span>}
          </div>
          {node.status === 'proposed' && <Evidence items={node.evidence} />}
          {canDecide && (
            <div className="flex gap-2 mt-1.5">
              <button disabled={busy} onClick={() => onDecide(node.casedoc_id, true)}
                      className="text-xs px-3 py-1 rounded-lg bg-emerald-600 text-white disabled:opacity-50">✓ تأكيد أنها فاتورة المريض</button>
              <button disabled={busy} onClick={() => onDecide(node.casedoc_id, false)}
                      className="text-xs px-3 py-1 rounded-lg border border-rose-300 text-rose-700 disabled:opacity-50">✕ ليست لها علاقة</button>
            </div>
          )}
        </div>
      </div>
      {open && kids.map((k) => <TreeNode key={k.id} node={k} depth={depth + 1} onDecide={onDecide} busy={busy} />)}
    </div>
  )
}

function ExceptionRow({ e, onDecide, busy }) {
  const [note, setNote] = useState('')
  const open = e.status === 'open' || e.status === 'acknowledged'
  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-center gap-2 flex-wrap">
        <Chip tone={SEV_TONE[e.severity]}>{SEV_LABEL[e.severity]}</Chip>
        <span className="font-medium text-sm">{e.type_label}</span>
        {e.amount && <span className="text-sm tabular-nums">{money(e.amount)}</span>}
        <Chip tone={open ? 'amber' : 'gray'}>{e.status_label}</Chip>
      </div>
      {e.detail && <div className="text-xs text-gray-600 mt-1">{e.detail}</div>}
      {e.evidence?.candidates && (
        <div className="text-[11px] text-gray-500 mt-1">
          مرشحات: {e.evidence.candidates.map((c) => `${c.voucher} (${money(c.amount)} · ${c.confidence})`).join('، ')}
        </div>
      )}
      {e.resolution && <div className="text-xs text-emerald-700 mt-1">✓ {e.resolution} {e.resolved_by_name && `— ${e.resolved_by_name}`}</div>}
      {open && (
        <div className="flex gap-2 mt-2 items-center">
          <input value={note} onChange={(x) => setNote(x.target.value)} placeholder="ملاحظة / سبب الحل"
                 className="border border-gray-300 rounded-lg px-2 py-1 text-xs flex-1" />
          {e.status === 'open' && (
            <button disabled={busy} onClick={() => onDecide(e.id, 'acknowledged', note)}
                    className="text-xs px-3 py-1 rounded-lg border border-gray-300">قيد المتابعة</button>
          )}
          <button disabled={busy || !note.trim()} onClick={() => onDecide(e.id, 'resolved', note)}
                  className="text-xs px-3 py-1 rounded-lg bg-gray-800 text-white disabled:opacity-40">تم الحل</button>
        </div>
      )}
    </div>
  )
}

const TABS = [['workflow', 'سير العمل'], ['docs', 'المستندات'], ['items', 'الأصناف'], ['ledger', 'دفتر الرصيد'], ['exceptions', 'الاستثناءات'], ['recon', 'المطابقة']]

export default function ReplacementCaseDetailPage() {
  const { id } = useParams()
  const qc = useQueryClient()
  const [tab, setTab] = useState(null)
  const [msg, setMsg] = useState('')
  const { data: c, isLoading, error } = useQuery({ queryKey: ['replacement-case', id],
                                                  queryFn: () => replacementApi.get(id).then((r) => r.data) })
  const done = (r) => { qc.setQueryData(['replacement-case', id], r.data); qc.invalidateQueries({ queryKey: ['replacement-list'] }); setMsg('') }
  const fail = (e) => setMsg(errText(e))
  const link = useMutation({ mutationFn: ({ cd, confirm }) => replacementApi.decideLink(id, cd, { confirm }), onSuccess: done, onError: fail })
  const exc = useMutation({ mutationFn: ({ eid, status, note }) => replacementApi.decideException(id, eid, { status, note }), onSuccess: done, onError: fail })
  const rebuild = useMutation({ mutationFn: () => replacementApi.rebuild(id), onSuccess: done, onError: fail })

  if (isLoading) return <div className="p-6 text-gray-400">جارٍ التحميل…</div>
  if (error) return <div className="p-6 text-rose-700">{errText(error, 'تعذّر تحميل الحالة')}</div>
  const busy = link.isPending || exc.isPending || rebuild.isPending
  const live = c.origin === 'live'
  const activeTab = tab || (live ? 'workflow' : 'docs')
  const openExc = c.exceptions.filter((e) => e.status === 'open' || e.status === 'acknowledged')

  return (
    <div className="p-4 space-y-4" dir="rtl">
      <div className="text-xs"><Link to="/replacement" className="text-blue-700">← كل الحالات</Link></div>

      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-lg font-bold font-mono">{c.number}</h1>
              <Chip tone={STATUS_TONE[c.status]}>{c.status_label}</Chip>
              <Chip tone="violet">{c.source_label}</Chip>
              <Chip tone="gray">{c.mode_label}</Chip>
              {c.origin === 'reconstructed' && <Chip tone="gray" title="بُنيت من التاريخ">📜 تاريخية</Chip>}
              {live && <Chip tone="teal">🟢 حالة تشغيلية v{c.version}</Chip>}
              {c.workflow?.locked && <Chip tone="gray">🔒 مقفلة</Chip>}
            </div>
            <div className="text-sm text-gray-800">
              {c.patient_name || <span className="text-gray-400">مريض غير معروف</span>}
              {c.softech_pic && <span className="font-mono text-gray-500"> · {c.softech_pic}</span>}
            </div>
            <div className="text-xs text-gray-500">
              فرع {c.branch_name} · تعاقد {c.contract_personcode || '—'} · مورد {c.supplier_personcode} {c.supplier_name && `(${c.supplier_name})`}
            </div>
            <div className="text-xs text-gray-500">
              سعر الجمهور {money(c.public_value)} · قيمة التعاقد {money(c.contract_value)} · الخصم المطبق {c.applied_deduction_pct ?? '—'}%
              {c.supplier_tier_pct && ` (فئة المورد ${Number(c.supplier_tier_pct)}%)`}
            </div>
          </div>
          <div className="flex gap-4">
            <div className="text-center"><div className="text-[11px] text-gray-500">الرصيد</div><div className="text-2xl font-bold tabular-nums">{money(c.entitlement)}</div></div>
            <div className="text-center"><div className="text-[11px] text-gray-500">المتبقي</div>
              <div className={`text-2xl font-bold tabular-nums ${Number(c.outstanding) > 0.01 ? 'text-rose-700' : 'text-emerald-700'}`}>{money(c.outstanding)}</div></div>
          </div>
        </div>
        <Rail c={c} />
        <div className="flex gap-2 flex-wrap text-xs">
          <Chip tone="emerald">منتجات {money(c.redeemed_products)}</Chip>
          <Chip tone="indigo">نقدي {money(c.redeemed_cash)}</Chip>
          {Number(c.redeemed_unclassified) > 0 && <Chip tone="amber">غير مصنّف {money(c.redeemed_unclassified)}</Chip>}
          {Number(c.absorbed) > 0 && <Chip tone="gray">فرق مستوعب {money(c.absorbed)}</Chip>}
          {Number(c.customer_topup) > 0 && <Chip tone="teal">دفع المريض {money(c.customer_topup)}</Chip>}
          {openExc.map((e) => <Chip key={e.id} tone={SEV_TONE[e.severity]}>⚠ {e.type_label}</Chip>)}
        </div>
      </div>

      {msg && <div className="bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-lg px-3 py-2">{msg}</div>}

      <div className="flex gap-1 border-b border-gray-200">
        {TABS.filter(([k]) => k !== 'workflow' || live).map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
                  className={`px-4 py-2 text-sm -mb-px border-b-2 ${activeTab === k ? 'border-blue-600 text-blue-700 font-medium' : 'border-transparent text-gray-500'}`}>
            {l}{k === 'exceptions' && openExc.length ? ` (${openExc.length})` : ''}
          </button>
        ))}
        <div className="flex-1" />
        <button disabled={busy} onClick={() => rebuild.mutate()} className="text-xs text-gray-500 px-2" title="إعادة بناء الحالة من بيانات SOFTECH (قراءة فقط)">⟳ إعادة البناء</button>
      </div>

      {activeTab === 'workflow' && <WorkflowPanel c={c} />}

      {activeTab === 'docs' && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <TreeNode node={c.tree} depth={0} busy={busy} onDecide={(cd, confirm) => link.mutate({ cd, confirm })} />
        </div>
      )}

      {activeTab === 'items' && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-[11px] text-gray-500"><tr>
              {['الصنف', 'الكود', 'الحالة', 'كمية الروشتة', 'كمية البدل', 'سعر الجمهور', 'سعر التعاقد', 'سعر الشراء', 'الخصم', 'قيمة الجمهور المؤهلة'].map((h) => <th key={h} className="px-3 py-2 text-right font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {c.items.map((i) => (
                <tr key={i.id} className={`border-t border-gray-100 ${i.disposition === 'selected_for_replacement' ? 'bg-amber-50' : ''}`}>
                  <td className="px-3 py-2">{i.item_name}</td>
                  <td className="px-3 py-2 font-mono text-xs">{i.itemcode}</td>
                  <td className="px-3 py-2"><Chip tone={i.disposition === 'selected_for_replacement' ? 'amber' : 'gray'}>{i.disposition_label}</Chip></td>
                  <td className="px-3 py-2 tabular-nums">{i.qty_prescribed ?? '—'}</td>
                  <td className="px-3 py-2 tabular-nums">{Number(i.qty_replaced) ? i.qty_replaced : '—'}</td>
                  <td className="px-3 py-2 tabular-nums">{money(i.public_unit_price)}</td>
                  <td className="px-3 py-2 tabular-nums">{money(i.contract_unit_price)}</td>
                  <td className="px-3 py-2 tabular-nums">{money(i.purchase_unit_price)}</td>
                  <td className="px-3 py-2 tabular-nums">{i.applied_deduction_pct != null ? `${i.applied_deduction_pct}%` : '—'}</td>
                  <td className="px-3 py-2 tabular-nums">{Number(i.qty_replaced) ? money(i.eligible_public_value) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'ledger' && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
          <div className="text-[11px] text-gray-500 px-3 pt-3">دفتر للإضافة فقط — أي تصحيح يظهر كقيد عكسي، ولا يُعدَّل أي قيد.</div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-[11px] text-gray-500"><tr>
              {['التاريخ', 'النوع', 'المبلغ', 'المستند', 'ملاحظة'].map((h) => <th key={h} className="px-3 py-2 text-right font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {c.ledger.map((e) => (
                <tr key={e.id} className={`border-t border-gray-100 ${e.entry_type === 'reversal' ? 'text-gray-400 line-through decoration-gray-300' : ''}`}>
                  <td className="px-3 py-2 text-xs whitespace-nowrap">{String(e.created_at).slice(0, 16).replace('T', ' ')}</td>
                  <td className="px-3 py-2">{e.type_label}</td>
                  <td className={`px-3 py-2 tabular-nums font-semibold ${Number(e.amount) > 0 ? 'text-emerald-700' : 'text-rose-700'}`}>{money(e.amount)}</td>
                  <td className="px-3 py-2 text-xs font-mono">{e.document_label}</td>
                  <td className="px-3 py-2 text-xs">{e.note}</td>
                </tr>
              ))}
              <tr className="border-t-2 border-gray-300 font-bold">
                <td className="px-3 py-2" colSpan={2}>الرصيد</td>
                <td className="px-3 py-2 tabular-nums">{money(c.outstanding)}</td>
                <td className="px-3 py-2 text-xs font-normal text-gray-500" colSpan={2}>SOFTECH: {money(c.native_outstanding)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {activeTab === 'exceptions' && (
        <div className="space-y-2">
          {!c.exceptions.length && <div className="text-sm text-gray-400 p-4">لا توجد استثناءات.</div>}
          {c.exceptions.map((e) => (
            <ExceptionRow key={e.id} e={e} busy={busy} onDecide={(eid, status, note) => exc.mutate({ eid, status, note })} />
          ))}
        </div>
      )}

      {activeTab === 'recon' && (
        <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-[11px] text-gray-500"><tr>
              {['البند', 'المتوقع', 'الفعلي', ''].map((h) => <th key={h} className="px-3 py-2 text-right font-medium">{h}</th>)}
            </tr></thead>
            <tbody>
              {c.reconciliation.map((r) => (
                <tr key={r.leg} className="border-t border-gray-100">
                  <td className="px-3 py-2">{r.leg}</td>
                  <td className="px-3 py-2 tabular-nums">{r.expected ? money(r.expected) : '—'}</td>
                  <td className="px-3 py-2 tabular-nums">{money(r.actual)}</td>
                  <td className="px-3 py-2">{r.ok ? '✓' : <span className="text-rose-700">✕</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-[11px] text-gray-400 p-3 font-mono">correlation {c.correlation_id} · rules {c.rules_version}</div>
        </div>
      )}
    </div>
  )
}
