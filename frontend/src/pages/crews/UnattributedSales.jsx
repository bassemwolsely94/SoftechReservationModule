/**
 * «بائع غير محدد» tab of /crews: per branch, the share of sales recorded on a generic or cashier-station
 * account instead of the real seller; below, the biggest selling accounts. With crews edit, a «حساب عام»
 * tick per code adds / removes it from the generic rule (PUT config, then refetch). A code that is generic
 * because of its SOFTECH group shows ticked and locked. Lowering the share is an operations matter.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { crewsApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import SortTh from '../../components/SortTh'
import { INPUT, TD, TH, errText, fmtInt, fmtMoney, fmtShare, monthStartIso, todayIso } from './util'

const getKey = s => s.code
const sellerValue = (s, k) => (k === 'display' ? (s.name || s.code) : s[k])

export default function UnattributedSales({ canEdit }) {
  const qc = useQueryClient()
  const [start, setStart] = useState(monthStartIso())
  const [end, setEnd] = useState(todayIso())
  const q = useQuery({
    queryKey: ['crews', 'unattributed', start, end],
    queryFn: () => crewsApi.unattributed({ start, end }).then(r => r.data),
    enabled: !!start && !!end,
  })
  const cfg = useQuery({ queryKey: ['crews', 'generic-config'], queryFn: () => crewsApi.genericConfig().then(r => r.data) })
  const rule = cfg.data?.rule || q.data?.rule || { groups: [], usercodes: [] }
  const groupNames = Object.fromEntries((cfg.data?.groups || []).map(g => [String(g.code), g.name]))
  const viaGroup = s => (rule.groups || []).map(String).includes(String(s.group ?? ''))
  const blank = s => !String(s.code || '').trim()          // a sale with no seller code is always unknown

  const branches = useSortableRows(q.data?.branches || [], { persistKey: 'crews-unattributed-branches' })
  const sellers = useSortableRows(q.data?.sellers || [], { persistKey: 'crews-unattributed-sellers', getValue: sellerValue })

  const setGeneric = useMutation({
    mutationFn: ({ code, on }) => {
      const codes = (rule.usercodes || []).map(String).filter(c => c !== String(code))
      return crewsApi.setGeneric({ groups: rule.groups || [], usercodes: on ? [...codes, String(code)] : codes })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['crews'] }),
  })
  const canToggle = s => canEdit && !blank(s) && !viaGroup(s) && !setGeneric.isPending && !!cfg.data
  const toggle = s => { if (canToggle(s)) setGeneric.mutate({ code: s.code, on: !s.generic }) }
  const kb = useGridKeyboard({ rows: sellers.sorted, getKey, onToggle: canEdit ? toggle : undefined })

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">
        المبيعات المسجلة على حساب عام أو حساب جهاز كاشير بدل البائع الحقيقي. خفض النسبة أمر تشغيلي: أن يبيع كل شخص بحسابه.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-gray-600">من</span>
        <input type="date" className={INPUT} value={start} max={end} onChange={e => setStart(e.target.value)} />
        <span className="text-gray-600">إلى</span>
        <input type="date" className={INPUT} value={end} min={start} onChange={e => setEnd(e.target.value)} />
      </div>
      {q.isLoading && <p className="text-sm text-gray-500">جارٍ التحميل…</p>}
      {q.isError && <p className="text-sm text-red-600">{errText(q.error)}</p>}

      <section className="card p-0 overflow-x-auto" data-tour="crews-unattributed-branches">
        <table className="w-full">
          <thead className="bg-gray-50"><tr>
            <SortTh {...branches.headerProps('label', 'text')} className={TH}>الفرع</SortTh>
            <SortTh {...branches.headerProps('invoices', 'number')} className={TH}>الفواتير</SortTh>
            <SortTh {...branches.headerProps('amount', 'number')} className={TH}>المبلغ</SortTh>
            <SortTh {...branches.headerProps('unattributed_amount', 'number')} className={TH}>بلا بائع محدد</SortTh>
            <SortTh {...branches.headerProps('share', 'number')} className={TH}>النسبة</SortTh>
          </tr></thead>
          <tbody className="divide-y divide-gray-100">
            {branches.sorted.map(b => (
              <tr key={b.branch_id}>
                <td className={TD}>{b.label}</td>
                <td className={`${TD} tabular-nums`}>{fmtInt(b.invoices)}</td>
                <td className={`${TD} tabular-nums`}>{fmtMoney(b.amount)}</td>
                <td className={`${TD} tabular-nums`}>{fmtMoney(b.unattributed_amount)}</td>
                <td className={`${TD} tabular-nums font-semibold`}>{fmtShare(b.share)}</td>
              </tr>
            ))}
            {q.data && branches.sorted.length === 0 && <tr><td colSpan={5} className={`${TD} text-gray-500`}>لا مبيعات في الفترة.</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="space-y-1">
        <h3 className="text-sm font-bold text-gray-800">حسابات البيع (الأكبر بالمبلغ)</h3>
        {(rule.groups || []).length > 0 && (
          <p className="text-xs text-gray-500">
            مجموعات SOFTECH المحسوبة حسابًا عامًا: {rule.groups.map(g => groupNames[String(g)] ? `${g} · ${groupNames[String(g)]}` : g).join('، ')}
          </p>
        )}
        {setGeneric.isError && <p className="text-xs text-red-600">{errText(setGeneric.error)}</p>}
        <div {...kb.containerProps} className={`card p-0 overflow-x-auto ${kb.containerProps.className}`} data-tour="crews-unattributed-sellers">
          <table className="w-full">
            <thead className="bg-gray-50"><tr>
              <SortTh {...sellers.headerProps('code', 'text')} className={TH}>الكود</SortTh>
              <SortTh {...sellers.headerProps('display', 'text')} className={TH}>الاسم</SortTh>
              <SortTh {...sellers.headerProps('group_name', 'text')} className={TH}>المجموعة</SortTh>
              <SortTh {...sellers.headerProps('invoices', 'number')} className={TH}>الفواتير</SortTh>
              <SortTh {...sellers.headerProps('amount', 'number')} className={TH}>المبلغ</SortTh>
              <SortTh {...sellers.headerProps('generic', 'text')} className={TH}>حساب عام</SortTh>
            </tr></thead>
            <tbody className="divide-y divide-gray-100">
              {sellers.sorted.map(s => (
                <tr key={s.code} {...kb.rowProps(s)}>
                  <td className={`${TD} tabular-nums`} dir="ltr">{s.code || '—'}</td>
                  <td className={TD}>{s.name || s.code || '—'}</td>
                  <td className={`${TD} text-xs`}>{s.group_name || s.group || '—'}</td>
                  <td className={`${TD} tabular-nums`}>{fmtInt(s.invoices)}</td>
                  <td className={`${TD} tabular-nums`}>{fmtMoney(s.amount)}</td>
                  <td className={TD}>
                    <label className="flex items-center gap-1 text-xs" title={viaGroup(s) ? 'عام بسبب مجموعته في SOFTECH' : undefined}>
                      <input type="checkbox" checked={!!s.generic} disabled={!canToggle(s)} onChange={() => toggle(s)} />
                      {blank(s) ? <span className="text-gray-500">بلا كود</span> : viaGroup(s) && <span className="text-gray-500">بالمجموعة</span>}
                    </label>
                  </td>
                </tr>
              ))}
              {q.data && sellers.sorted.length === 0 && <tr><td colSpan={6} className={`${TD} text-gray-500`}>لا حسابات بيع في الفترة.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
