/**
 * SourcePanel.jsx — «مصدر القيد»: the SOFTECH documents behind a drafted entry.
 *
 * Read-only drill-down inside EntryEditor: every member document (SOFTECH key, date, branch,
 * the amounts the rule used, version) plus the rule code/version that built the entry.
 * Collapsed by default so the entry editor stays calm.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import useSortableRows from '../../../hooks/useSortableRows'
import SortTh from '../../../components/SortTh'
import { money, errOf, useGlBranches, ErrorBox } from './glUi'
import { SOURCE_TYPES } from './RuleEditor'

const DOC_STATUS = { new: 'جديد', drafted: 'مرحّل', skipped: 'مُتجاوز', exception: 'استثناء', vanished: 'اختفى', changed: 'تغيّر' }

const fmtTs = (t) => (t ? t.replace('T', ' ').slice(0, 16) : '—')
function attrsText(attrs) {
  const e = Object.entries(attrs || {})
  return e.length ? e.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(',') : (typeof v === 'object' && v ? JSON.stringify(v) : v)}`).join(' · ') : '—'
}

export function amountsText(amounts) {
  const e = Object.entries(amounts || {})
  return e.length ? e.map(([k, v]) => `${k} ${money(v)}`).join(' · ') : '—'
}

export default function SourcePanel({ entryId }) {
  const [open, setOpen] = useState(false)
  const { branches, labelOf } = useGlBranches()
  const branchName = (code) => {
    const b = branches.find(x => String(x.softech_branch_id) === String(code))
    return b ? labelOf(b.id) : '—'
  }
  const q = useQuery({
    queryKey: ['gl', 'entry-source', entryId],
    queryFn: () => glApi.entrySource(entryId).then(r => r.data.docs || []),
    enabled: open,
  })
  const rows = (q.data || []).map(d => ({ ...d, _branch: branchName(d.branch_code), _amounts: amountsText(d.amounts) }))
  const { sorted, headerProps } = useSortableRows(rows, {
    persistKey: 'gl-entry-source', defaultSort: { key: 'doc_date', dir: 'asc', type: 'date' },
  })
  const rule = rows.find(r => r.rule_code)

  return (
    <div className="border border-gray-200 rounded-lg" data-tour="finance-gl-entry-source">
      <button type="button" className="w-full flex items-center gap-2 px-3 py-2 text-sm text-right hover:bg-gray-50"
              onClick={() => setOpen(o => !o)}>
        <span className="text-gray-400">{open ? '▾' : '◂'}</span>
        <span className="font-medium text-gray-700">مصدر القيد (مستندات SOFTECH)</span>
        {open && q.data && <span className="text-xs text-gray-500">{rows.length} مستند</span>}
      </button>
      {open && (
        <div className="border-t border-gray-100 p-3 space-y-2">
          <ErrorBox>{q.isError ? errOf(q.error, 'تعذّر تحميل المصدر') : ''}</ErrorBox>
          {q.isLoading && <div className="text-xs text-gray-500">جاري التحميل…</div>}
          {q.data && !rows.length && <div className="text-xs text-gray-500">لا مستندات مرتبطة بهذا القيد</div>}
          {rule && (
            <div className="text-xs text-gray-600">
              القاعدة: <Link className="text-green-700 hover:underline font-mono" to={`/finance/rules?code=${encodeURIComponent(rule.rule_code)}`}>{rule.rule_code}</Link>
              {' '}— النسخة {rule.rule_version}
              {rule.source_type && <> · {SOURCE_TYPES[rule.source_type] || rule.source_type}</>}
            </div>
          )}
          {!!rows.length && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-gray-600">
                  <tr>
                    <SortTh {...headerProps('source_key', 'text')} className="text-right px-2 py-1.5">مفتاح SOFTECH</SortTh>
                    <SortTh {...headerProps('doc_date', 'date')} className="text-right px-2 py-1.5">التاريخ</SortTh>
                    <SortTh {...headerProps('_branch')} className="text-right px-2 py-1.5">الفرع</SortTh>
                    <SortTh {...headerProps('_amounts')} className="text-right px-2 py-1.5">المبالغ</SortTh>
                    <th className="text-right px-2 py-1.5">الخصائص</th>
                    <SortTh {...headerProps('version', 'number')} className="text-right px-2 py-1.5">النسخة</SortTh>
                    <SortTh {...headerProps('status')} className="text-right px-2 py-1.5">الحالة</SortTh>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(d => (
                    <tr key={d.id} className="border-t border-gray-100 align-top">
                      <td className="px-2 py-1 font-mono break-all" dir="ltr">{d.source_key}</td>
                      <td className="px-2 py-1 whitespace-nowrap">{d.doc_date}</td>
                      <td className="px-2 py-1">{d._branch}</td>
                      <td className="px-2 py-1 font-mono tabular-nums" dir="ltr">{d._amounts}</td>
                      <td className="px-2 py-1 text-gray-600 max-w-xs break-words" dir="ltr">{attrsText(d.attrs)}</td>
                      <td className="px-2 py-1 whitespace-nowrap" title={`بصمة ${d.content_hash || ''}`}>
                        {d.version}
                        <div className="text-[10px] text-gray-400">أول ظهور {fmtTs(d.first_seen)}<br />آخر ظهور {fmtTs(d.last_seen)}</div>
                      </td>
                      <td className="px-2 py-1">{DOC_STATUS[d.status] || d.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
