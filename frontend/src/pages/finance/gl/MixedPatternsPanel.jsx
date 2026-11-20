/**
 * MixedPatternsPanel.jsx — «حسب النمط»: the parked «قيد يدوي مختلط» groups of finance's journal,
 * one row per pattern (book + manual accounts + SOFTECH accounts). An accountant imports a whole
 * pattern as drafts or ignores it with a reason. The server decides and refuses a pattern whose
 * count changed since this list loaded; nothing here approves an entry.
 */
import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import useSortableRows from '../../../hooks/useSortableRows'
import useGridKeyboard, { GRID_KEYS_HINT } from '../../../hooks/useGridKeyboard'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import { money, errOf, inputCls, btnPrimary, btnPlain, ErrorBox } from './glUi'

const BOOK = { cash: 'النقدية', credit: 'الآجل', general: 'عام' }

function Decide({ p, onDone }) {
  const [mode, setMode] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const go = useMutation({
    mutationFn: () => glApi.mixedPatternDecide({
      pattern: p.pattern, decision: mode, expected_count: p.count, note: mode === 'ignore' ? note.trim() : '',
    }).then(r => r.data),
    onSuccess: (d) => {
      setErr('')
      const failed = d.failed?.length ? ` · ${d.failed.length} اترفضوا وفضلوا مفتوحين (${d.failed[0].detail})` : ''
      onDone(mode === 'ignore' ? `اتجاهل ${d.ignored} قيد` : `اتعمل ${d.imported + d.already_imported} مسودة${failed}`)
    },
    onError: (e) => {
      if (e?.response?.status === 409) onDone('', 'العدد اتغيّر من ساعة ما فتحت الشاشة — القائمة اتحدّثت، راجع تاني')
      else setErr(errOf(e, 'تعذّر تنفيذ القرار'))
    },
  })
  if (!mode) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btnPrimary} onClick={() => setMode('import')}>استيراد الكل كقيود</button>
        <button type="button" className={btnPlain} onClick={() => setMode('ignore')}>تجاهل الكل</button>
        <span className="text-xs text-gray-500">الاستيراد بيعمل مسودات بس — الاعتماد بعدها من اليومية زي أي قيد.</span>
      </div>
    )
  }
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={e => { e.preventDefault(); go.mutate() }}>
      <span className="text-sm">
        {mode === 'import' ? `هيتعمل ${p.count} مسودة من أسطر القيود زي ما هي.` : `هيتجاهل ${p.count} قيد.`}
      </span>
      {mode === 'ignore' && (
        <input className={`${inputCls} w-72`} placeholder="السبب (مطلوب) — مثلاً: سوفتيك بيغطيه" value={note}
               maxLength={2000} onChange={e => setNote(e.target.value)} autoFocus />
      )}
      <button type="submit" className={btnPrimary} disabled={go.isPending || (mode === 'ignore' && !note.trim())}>
        {go.isPending ? 'جاري التنفيذ…' : `تأكيد (${p.count})`}
      </button>
      <button type="button" className={btnPlain} disabled={go.isPending} onClick={() => { setMode(''); setErr('') }}>رجوع</button>
      <ErrorBox>{err}</ErrorBox>
    </form>
  )
}

export default function MixedPatternsPanel({ canCreate }) {
  const qc = useQueryClient()
  const [openRow, setOpenRow] = useState(null)
  const [msg, setMsg] = useState('')
  const [warn, setWarn] = useState('')
  const listQ = useQuery({ queryKey: ['gl', 'exceptions', 'mixed-patterns'], queryFn: () => glApi.mixedPatterns().then(r => r.data) })
  const rows = useMemo(() => (listQ.data?.results || []).map(p => ({
    ...p, _book: BOOK[p.book] || p.book, _manual: p.manual_accounts.join('، '), _softech: p.softech_accounts.join('، ') || '—',
    _debit: Number(p.debit),
  })), [listQ.data])
  const { sorted, headerProps } = useSortableRows(rows, {
    persistKey: 'gl-mixed-patterns', defaultSort: { key: 'count', dir: 'desc', type: 'number' },
  })
  const kb = useGridKeyboard({
    rows: sorted, getKey: r => r.pattern,
    onConfirm: (r) => setOpenRow(o => (o === r.pattern ? null : r.pattern)), onClose: () => setOpenRow(null),
  })
  const done = (text, warning) => {
    setMsg(text || ''); setWarn(warning || ''); setOpenRow(null)
    qc.invalidateQueries({ queryKey: ['gl', 'exceptions'] })
  }

  return (
    <div className="space-y-2">
      {msg && <div className="text-sm text-green-700">{msg}</div>}
      {warn && <div className="text-sm text-amber-700">{warn}</div>}
      <ErrorBox>{listQ.isError ? errOf(listQ.error, 'تعذّر تحميل الأنماط') : ''}</ErrorBox>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" {...kb.containerProps}>
        {listQ.isLoading ? <SkeletonTable rows={6} cols={7} /> : !sorted.length ? (
          <EmptyState title="مفيش قيود مختلطة مفتوحة" sub="كل قيود يومية المالية المختلطة اتقرر فيها" />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...headerProps('_book')} className="text-right px-3 py-2">الدفتر</SortTh>
                <SortTh {...headerProps('_manual')} className="text-right px-3 py-2">حسابات يدوية</SortTh>
                <SortTh {...headerProps('_softech')} className="text-right px-3 py-2">حسابات سوفتيك</SortTh>
                <SortTh {...headerProps('count', 'number')} className="text-left px-3 py-2">عدد القيود</SortTh>
                <SortTh {...headerProps('_debit', 'number')} className="text-left px-3 py-2">الإجمالي</SortTh>
                <SortTh {...headerProps('date_from', 'date')} className="text-right px-3 py-2">من – إلى</SortTh>
                <th className="text-right px-3 py-2">أمثلة</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(r => {
                const kbp = kb.rowProps(r)
                const isOpen = openRow === r.pattern
                return (
                  <Fragment key={r.pattern}>
                    <tr {...kbp} className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${isOpen ? 'bg-blue-50/60' : ''} ${kbp.className}`}
                        onClick={() => setOpenRow(isOpen ? null : r.pattern)}>
                      <td className="px-3 py-1.5">{r._book}</td>
                      <td className="px-3 py-1.5 font-mono text-xs">{r._manual}</td>
                      <td className="px-3 py-1.5 font-mono text-xs">{r._softech}</td>
                      <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{r.count}</td>
                      <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(r.debit)}</td>
                      <td className="px-3 py-1.5 whitespace-nowrap text-xs">{r.date_from} – {r.date_to}</td>
                      <td className="px-3 py-1.5 text-xs text-gray-600">{r.samples.join(' · ')}</td>
                    </tr>
                    {isOpen && canCreate && (
                      <tr className="bg-gray-50/70"><td colSpan={7} className="px-4 py-3" onClick={e => e.stopPropagation()}>
                        <Decide p={r} onDone={done} />
                      </td></tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
      <div className="text-xs text-gray-400">{GRID_KEYS_HINT.replace('Enter تأكيد · M مطابقة', 'Enter قرار')}</div>
    </div>
  )
}
