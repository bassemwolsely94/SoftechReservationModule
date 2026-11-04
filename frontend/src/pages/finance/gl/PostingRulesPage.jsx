/**
 * PostingRulesPage.jsx — «قواعد الترحيل»
 * Route: /finance/rules   (tabs: rules | maps)
 *
 * The finance-editable rules that turn SOFTECH documents into draft ledger entries, and the maps
 * (bank / expense / card-clearing) the rules read. Editing a rule creates a new version; nothing
 * is deleted. View needs ledger.view, edits need ledger.edit — the server enforces both.
 */
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import RuleEditor, { SOURCE_TYPES, summarizeConditions, summarizeLines } from './RuleEditor'
import SourceMapsPanel from './SourceMapsPanel'
import { errOf, listOf, useGlBranches, inputCls, btnPrimary, ErrorBox } from './glUi'

const GRANULARITY = { document: 'مستند', branch_day: 'فرع/يوم', party_day: 'طرف/يوم' }

export default function PostingRulesPage() {
  const perms = usePermissions('ledger')
  const { branches, labelOf } = useGlBranches()
  const branchName = (code) => { const b = branches.find(x => String(x.softech_branch_id) === String(code)); return b ? labelOf(b.id) : code }
  const [tab, setTab] = useState('rules')
  useHelpTab(tab)
  const [source, setSource] = useState('')
  const [onlyActive, setOnlyActive] = useState(true)
  const [open, setOpen] = useState(null)       // rule json | 'new' | null

  const rulesQ = useQuery({
    queryKey: ['gl', 'rules', source, onlyActive],
    queryFn: () => glApi.rules({ source_type: source || undefined, active: onlyActive ? '1' : undefined }).then(r => listOf(r.data)),
  })
  const rows = useMemo(() => (rulesQ.data || []).map(r => ({
    ...r, _cond: summarizeConditions(r.conditions, branchName), _lines: summarizeLines(r.lines, r.action),
    _dates: `${r.effective_from || ''} ${r.effective_to || ''}`,
  })), [rulesQ.data, branches]) // eslint-disable-line react-hooks/exhaustive-deps
  const { sorted, headerProps } = useSortableRows(rows, {
    persistKey: 'gl-rules', defaultSort: { key: 'source_type', dir: 'asc', type: 'text' },
  })
  const [params] = useSearchParams()
  const wantCode = params.get('code')
  useEffect(() => {   // /finance/rules?code=... opens that rule (from the entry source panel)
    if (!wantCode || open) return
    const hit = rows.find(r => r.code === wantCode)
    if (hit) setOpen(hit)
  }, [wantCode, rows]) // eslint-disable-line react-hooks/exhaustive-deps
  const editing = open && open !== 'new' ? rows.find(r => r.code === open.code) || open : null

  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm w-fit">
        {[['rules', 'القواعد'], ['maps', 'الربط']].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
                  className={`px-4 py-1.5 ${tab === k ? 'bg-green-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{l}</button>
        ))}
      </div>

      {tab === 'maps' ? <SourceMapsPanel canEdit={!!perms.edit} /> : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <select className={inputCls} value={source} onChange={e => setSource(e.target.value)}>
              <option value="">كل المصادر</option>
              {Object.entries(SOURCE_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <label className="flex items-center gap-1 text-sm text-gray-600">
              <input type="checkbox" checked={onlyActive} onChange={e => setOnlyActive(e.target.checked)} /> النشطة فقط
            </label>
            {perms.edit && <button type="button" className={`${btnPrimary} ms-auto`} onClick={() => setOpen('new')}>+ قاعدة جديدة</button>}
          </div>
          <ErrorBox>{rulesQ.isError ? errOf(rulesQ.error, 'تعذّر تحميل القواعد') : ''}</ErrorBox>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] items-start">
            <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="finance-gl-rules-grid">
              {rulesQ.isLoading ? <SkeletonTable rows={8} cols={6} /> : !sorted.length ? (
                <EmptyState title="لا توجد قواعد" sub="شغّل أمر seed_gl_drafting أو أضف قاعدة جديدة" />
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-gray-600 text-xs">
                    <tr>
                      <SortTh {...headerProps('source_type', 'text')} className="text-right px-3 py-2">المصدر</SortTh>
                      <SortTh {...headerProps('code', 'text')} className="text-right px-3 py-2">الكود</SortTh>
                      <SortTh {...headerProps('version', 'number')} className="text-right px-3 py-2">النسخة</SortTh>
                      <SortTh {...headerProps('_cond')} className="text-right px-3 py-2">الشروط</SortTh>
                      <SortTh {...headerProps('_lines')} className="text-right px-3 py-2">الأسطر</SortTh>
                      <SortTh {...headerProps('granularity')} className="text-right px-3 py-2">التجميع</SortTh>
                      <SortTh {...headerProps('effective_from', 'date')} className="text-right px-3 py-2">يسري</SortTh>
                      <SortTh {...headerProps('is_active')} className="text-right px-3 py-2">نشطة</SortTh>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map(r => (
                      <tr key={r.id} onClick={() => setOpen(r)}
                          className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${editing?.code === r.code ? 'bg-green-50' : ''} ${r.is_active ? '' : 'text-gray-400'}`}>
                        <td className="px-3 py-1.5">{SOURCE_TYPES[r.source_type] || r.source_type}</td>
                        <td className="px-3 py-1.5 font-mono">{r.code}</td>
                        <td className="px-3 py-1.5">v{r.version}</td>
                        <td className="px-3 py-1.5 text-xs">{r._cond}</td>
                        <td className="px-3 py-1.5 text-xs font-mono">{r._lines}</td>
                        <td className="px-3 py-1.5">{GRANULARITY[r.granularity] || r.granularity}</td>
                        <td className="px-3 py-1.5 text-xs">{r.effective_from}{r.effective_to ? ` ← ${r.effective_to}` : ''}</td>
                        <td className="px-3 py-1.5">{r.is_active ? '✓' : '✗'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {open && (
              <RuleEditor key={open === 'new' ? 'new' : `${open.code}`} rule={open === 'new' ? null : editing}
                          canEdit={!!perms.edit} onClose={() => setOpen(null)}
                          onSaved={(r) => { if (open === 'new') setOpen(r) }} />
            )}
          </div>
        </>
      )}
    </div>
  )
}
