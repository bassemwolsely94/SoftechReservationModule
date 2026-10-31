/**
 * ReceiptCheckTab — /supply «استلام بدون طلب» (P-31).
 *
 * Purchase lines from the pilot suppliers checked against the need sheets actually sent: every download of the
 * demand pivot (`Total.الفرق-مطلوب/راكد`) is kept. «بدون طلب — ارجعه» = the item was on no sheet in the window;
 * «زيادة عن الفرق المطلوب» = more arrived than the sheet asked for. The server decides the flags and checks the
 * rights; the return itself is a doc 120 entered in SOFTECH, which closes the row on the next check.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import useBranchLabels from '../../hooks/useBranchLabels'
import useGridKeyboard, { GRID_KEYS_HINT } from '../../hooks/useGridKeyboard'
import ProgressBar from '../../components/ProgressBar'
import { Chip, q, money, errText, inputCls, btnPrimary, btnGhost, SortTh, useSort } from './supplyUi'

const STATUS = [['open', 'مفتوح'], ['return_requested', 'مرتجع مطلوب'], ['accepted', 'مقبول'], ['returned', 'تم الإرجاع'], ['all', 'الكل']]
const FLAG_TONE = { unordered: 'rose', over: 'amber' }

export default function ReceiptCheckTab() {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [status, setStatus] = useState('open')
  const [reasons, setReasons] = useState({})       // row id → accept reason
  const [msg, setMsg] = useState('')
  const [since, setSince] = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['supply-receipts', status],
    queryFn: () => supplyApi.receipts({ status }).then(r => r.data),
  })
  const rows = data?.rows || []
  const reload = () => qc.invalidateQueries({ queryKey: ['supply-receipts'] })
  const decide = useMutation({
    mutationFn: ({ id, action, reason }) => supplyApi.receiptDecide(id, { action, reason }),
    onSuccess: () => { setMsg(''); reload() },
    onError: (e) => setMsg(errText(e)),
  })
  const refresh = useMutation({
    mutationFn: () => { setSince(Date.now()); return supplyApi.refreshPurchases() },
    onSuccess: (r) => { setSince(null); setMsg(`${r.data.detail} الفحص يُعاد تلقائياً بعد انتهاء التحديث.`) },
    onError: (e) => { setSince(null); setMsg(errText(e)) },
  })

  const grid = useSort(rows, {
    date: r => r.doc_date, supplier: r => r.supplier_name, item: r => r.item_name, qty: r => r.qty,
    value: r => r.value, flag: r => r.flag, age: r => r.age_days,
  })
  const accept = (r) => {
    const reason = reasons[r.id] || data?.accept_reasons?.[0] || ''
    decide.mutate({ id: r.id, action: 'accept', reason })
  }
  const kb = useGridKeyboard({
    rows: grid.sorted, getKey: r => r.id,
    onConfirm: (r) => r.status === 'open' && decide.mutate({ id: r.id, action: 'return' }),
  })
  const totals = useMemo(() => ({ n: rows.length, value: rows.reduce((s, r) => s + r.value, 0) }), [rows])

  return (
    <div className="space-y-3">
      <div className="text-sm text-content/80 bg-surface-2/60 border border-line rounded p-3 leading-6">
        كل تنزيل لشيت «الاحتياج» (Pivot) من «المشتريات» يُحفظ كما أُرسل للمورد. أي فاتورة شراء من الموردين
        {' '}{(data?.pilot_suppliers || []).join(' و')}{' '}
        لصنف لم يكن في شيت خلال آخر {data?.window_days ?? 14} يوماً تظهر هنا «بدون طلب»، وما وصل أكثر من «الفرق المطلوب» يظهر «زيادة».
        الإرجاع نفسه مستند 120 في SOFTECH، ويُغلق السطر تلقائياً عند ظهوره.
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <select value={status} onChange={e => setStatus(e.target.value)} className={inputCls}>
          {STATUS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span className="text-content/70">{totals.n} سطر · {money(totals.value)}</span>
        <span className="flex-1" />
        <button onClick={() => refresh.mutate()} disabled={refresh.isPending} className={btnGhost}>⟳ المشتريات من SOFTECH</button>
      </div>
      {refresh.isPending && <ProgressBar label="تحديث المشتريات" since={since} />}
      {msg && <div className="text-sm bg-surface-2 border border-line rounded px-3 py-2">{msg}</div>}

      {isLoading ? <div className="text-center py-10 text-content/50">جارٍ التحميل…</div> : rows.length === 0 ? (
        <div className="text-center py-14 text-content/50">لا توجد سطور — كل ما وصل كان في شيت احتياج مُرسَل.</div>
      ) : (
        <div data-tour="purchasing-supply-receipts-grid" {...kb.containerProps}
             className={`overflow-x-auto rounded-lg border border-line ${kb.containerProps.className}`}>
          <table className="w-full text-sm whitespace-nowrap">
            <thead className="bg-surface-2 text-content/70 text-xs">
              <tr>
                <SortTh k="date" {...grid} className="px-2 py-2 text-right">التاريخ</SortTh>
                <SortTh k="supplier" {...grid} className="px-2 py-2 text-right">المورد</SortTh>
                <th className="px-2 py-2 text-right">الفرع / المستند</th>
                <SortTh k="item" {...grid} className="px-2 py-2 text-right">الصنف</SortTh>
                <SortTh k="qty" {...grid} className="px-2 py-2 text-right">الكمية</SortTh>
                <SortTh k="value" {...grid} className="px-2 py-2 text-right">القيمة</SortTh>
                <SortTh k="flag" {...grid} className="px-2 py-2 text-right">الملاحظة</SortTh>
                <th className="px-2 py-2 text-right">الشيت المُرسَل</th>
                <SortTh k="age" {...grid} className="px-2 py-2 text-right">منذ</SortTh>
                <th className="px-2 py-2 text-right">القرار</th>
              </tr>
            </thead>
            <tbody>
              {grid.sorted.map(r => {
                const rp = kb.rowProps(r)
                return (
                  <tr key={r.id} {...rp} className={`border-t border-line ${rp.className}`}>
                    <td className="px-2 py-1.5">{r.doc_date}</td>
                    <td className="px-2 py-1.5">{r.supplier_name || r.supplier_code}</td>
                    <td className="px-2 py-1.5 text-xs">{bl(r.branch_code)} · #{r.doc_number}</td>
                    <td className="px-2 py-1.5">{r.item_name || r.item_code} <span className="text-xs text-content/50">{r.item_code}</span></td>
                    <td className="px-2 py-1.5">{q(r.qty)}</td>
                    <td className="px-2 py-1.5">{money(r.value)}</td>
                    <td className="px-2 py-1.5"><Chip tone={FLAG_TONE[r.flag]}>{r.flag_label}</Chip></td>
                    <td className="px-2 py-1.5 text-xs">
                      {r.sheet_date
                        ? <>{r.sheet_date} · الفرق المطلوب {q(r.sheet_gap)} · وصل {q(r.received_in_window)}
                            {r.sheet_supplier_code && r.sheet_supplier_code !== r.supplier_code &&
                              <div className="text-content/60">المورد بالشيت: {r.sheet_supplier_name || r.sheet_supplier_code}</div>}</>
                        : <span className="text-content/50">لم يكن في أي شيت</span>}
                    </td>
                    <td className="px-2 py-1.5">{r.age_days} يوم</td>
                    <td className="px-2 py-1.5">
                      {r.status === 'open' ? (
                        <span className="flex items-center gap-1">
                          <button className={btnPrimary} disabled={decide.isPending}
                                  onClick={() => decide.mutate({ id: r.id, action: 'return' })}>مرتجع مطلوب</button>
                          <select className={inputCls} value={reasons[r.id] || data?.accept_reasons?.[0] || ''}
                                  onChange={e => setReasons(x => ({ ...x, [r.id]: e.target.value }))}>
                            {(data?.accept_reasons || []).map(x => <option key={x} value={x}>{x}</option>)}
                          </select>
                          <button className={btnGhost} disabled={decide.isPending} onClick={() => accept(r)}>مقبول</button>
                        </span>
                      ) : (
                        <span className="flex items-center gap-1">
                          <Chip tone={r.status === 'returned' ? 'emerald' : 'gray'}>{r.status_label}</Chip>
                          {r.decision_reason && <span className="text-xs text-content/60">{r.decision_reason}</span>}
                          {r.status === 'returned' && <span className="text-xs">{money(r.returned_value)}</span>}
                          {r.status !== 'returned' && (
                            <button className="text-xs underline text-content/60"
                                    onClick={() => decide.mutate({ id: r.id, action: 'reopen' })}>إعادة فتح</button>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-xs text-content/50">{GRID_KEYS_HINT.replace(' · M مطابقة', '').replace(' · مسافة تحديد', '').replace(' · Ctrl+A تحديد الكل', '')} (Enter = مرتجع مطلوب)</div>
    </div>
  )
}
