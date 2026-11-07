/**
 * SoftechComparePage.jsx — «مقارنة سوفتيك»
 * Route: /finance/softech-compare?period=<id>[&check=<key>][&unexplained=1]
 *
 * The ledger beside SOFTECH for one month: a grid of check × branch (or supplier) with ledger / SOFTECH / difference.
 * A line whose difference is over its tolerance and unexplained is red. A row opens a side panel with the by-day table,
 * the ledger lines and the SOFTECH rows, and the inline explanation box. «تحديث الآن» recomputes in the background
 * (the server reads SOFTECH); the screen polls the stored lines, which never read SOFTECH. The server decides every
 * figure and every «needs explanation».
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import useBranchLabels from '../../../hooks/useBranchLabels'
import SortTh from '../../../components/SortTh'
import DataFreshnessBar from '../../../components/DataFreshnessBar'
import ProgressBar from '../../../components/ProgressBar'
import { SkeletonTable, EmptyState, Spinner } from '../../../components/ui'
import { money, errOf, OPENING_DATE, inputCls, btnPrimary, btnPlain, ErrorBox } from './glUi'

const num = 'px-3 py-1.5 text-left font-mono tabular-nums'
const POLL_MS = 3000
const GIVE_UP_MS = 10 * 60 * 1000

const whoOf = (l) => (l.per_party ? (l.party_name || 'بدون طرف') : (l.branch_name || '—'))
const getValue = (row, key) => (key === 'who' ? whoOf(row) : key === 'state' ? (row.needs_explanation ? 0 : row.explanation ? 1 : 2) : row[key])

// ── side panel ───────────────────────────────────────────────────────────────

/** A SOFTECH detail row: the fields differ by source, so name what is there. */
function softechWhat(r) {
  const bits = [r.kind && ({ opening: 'رصيد أول الشهر', invoice: 'فاتورة', return: 'مرتجع', payment: 'سداد' }[r.kind] || r.kind),
    r.ref, r.docnumber && `${r.doccode ? `${r.doccode}/` : ''}${r.docnumber}`, r.party, r.store_name, r.expcode, r.note,
    r.rows != null && `${r.rows} صنف`, r.carried && 'مرحّل'].filter(Boolean)
  return bits.join(' · ') || '—'
}

function DetailTable({ title, tour, children }) {
  return (
    <div className="space-y-1" data-tour={tour}>
      <div className="text-sm font-medium text-gray-700">{title}</div>
      <div className="rounded-lg border border-gray-200 overflow-x-auto">{children}</div>
    </div>
  )
}

function ComparePanel({ lineId, perms, onClose, onChanged }) {
  const bl = useBranchLabels()
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [err, setErr] = useState('')
  const q = useQuery({
    queryKey: ['gl', 'compare-line', lineId],
    queryFn: () => glApi.compareLine(lineId).then(r => r.data),
    retry: false,
  })
  const line = q.data?.line
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const explain = useMutation({
    mutationFn: () => glApi.compareExplain(lineId, text.trim()).then(r => r.data),
    onSuccess: (d) => {
      setErr(''); setText('')
      qc.setQueryData(['gl', 'compare-line', lineId], (old) => (old ? { ...old, line: d } : old))
      onChanged()
    },
    onError: (e) => setErr(errOf(e, 'تعذّر حفظ التفسير')),
  })

  const d = q.data
  const ledgerLines = d?.ledger || []
  const softech = d?.softech || []
  const byDay = d?.by_day
  return (
    <div className="fixed inset-y-0 left-0 z-40 w-full max-w-[1000px] bg-white shadow-2xl border-e border-gray-200 flex flex-col" dir="rtl"
         data-tour="finance-gl-compare-detail">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200">
        <h2 className="text-lg font-bold text-gray-900">{line ? `${line.check_label} — ${whoOf(line)}` : 'تفاصيل المقارنة'}</h2>
        <button type="button" onClick={onClose} className="ms-auto text-gray-400 hover:text-gray-700 text-xl" title="إغلاق (Esc)">×</button>
      </div>
      {q.isLoading ? <div className="p-8 flex justify-center"><Spinner size="md" /></div>
        : q.isError ? <div className="p-4"><ErrorBox>{errOf(q.error, 'تعذّر تحميل التفاصيل')}</ErrorBox></div> : (
        <div className="flex-1 overflow-auto p-4 space-y-4">
          <div className="grid grid-cols-3 gap-3 text-sm">
            {[['الدفتر', line.ledger_amount], ['سوفتيك', line.softech_amount], ['الفرق', line.difference]].map(([l, v]) => (
              <div key={l} className="rounded-lg border border-gray-200 px-3 py-2">
                <div className="text-xs text-gray-500">{l}</div>
                <div className={`font-mono tabular-nums text-lg ${l === 'الفرق' && line.needs_explanation ? 'text-red-700 font-bold' : ''}`} dir="ltr">{money(v)}</div>
              </div>
            ))}
          </div>

          {/* the explanation */}
          <div className="rounded-lg border border-gray-200 p-3 space-y-2 text-sm">
            <div className="font-medium text-gray-700">
              التفسير
              {line.needs_explanation
                ? <span className="ms-2 text-xs text-red-700">يحتاج تفسير</span>
                : line.explanation ? <span className="ms-2 text-xs text-green-700">مفسَّر</span> : <span className="ms-2 text-xs text-gray-400">في حدود التسامح</span>}
            </div>
            {line.explanation && (
              <div className="rounded bg-gray-50 px-3 py-2 whitespace-pre-wrap">
                {line.explanation}
                <div className="text-xs text-gray-500 mt-1">{line.explained_by_name}{line.explained_at ? ` · ${String(line.explained_at).slice(0, 10)}` : ''}
                  {line.explained_difference != null && ` · على فرق ${money(line.explained_difference)}`}</div>
              </div>
            )}
            {line.explanation && line.needs_explanation && (
              <div className="text-xs text-amber-700">الفرق اتغيّر بعد التفسير — اكتب تفسيراً جديداً.</div>
            )}
            {perms.approve && (
              <div className="space-y-2">
                <textarea className={`${inputCls} w-full`} rows={2} maxLength={1000} value={text} onChange={e => setText(e.target.value)}
                          placeholder="سبب الفرق (مثلاً: قيد بتاريخ مختلف، فاتورة لسه مش مرحّلة)" />
                <div className="flex items-center gap-3">
                  <button type="button" className={btnPrimary} disabled={!text.trim() || explain.isPending} onClick={() => explain.mutate()}>
                    {explain.isPending ? 'جارٍ الحفظ…' : 'حفظ التفسير'}
                  </button>
                  <ErrorBox>{err}</ErrorBox>
                </div>
              </div>
            )}
          </div>

          {byDay && (
            <DetailTable title="الفرق باليوم">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-600 text-xs"><tr>
                  <th className="text-right px-3 py-2">اليوم</th><th className="text-left px-3 py-2">الدفتر</th>
                  <th className="text-left px-3 py-2">سوفتيك</th><th className="text-left px-3 py-2">الفرق</th></tr></thead>
                <tbody>
                  {byDay.map(r => (
                    <tr key={r.date} className="border-t border-gray-100">
                      <td className="px-3 py-1.5">{r.date}</td>
                      <td className={num} dir="ltr">{money(r.ledger)}</td>
                      <td className={num} dir="ltr">{money(r.softech)}</td>
                      <td className={`${num} ${Number(r.difference) !== 0 ? 'text-red-700' : 'text-gray-400'}`} dir="ltr">{money(r.difference)}</td>
                    </tr>
                  ))}
                  {!byDay.length && <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">لا حركة</td></tr>}
                </tbody>
              </table>
            </DetailTable>
          )}

          <DetailTable title="سطور الدفتر">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs"><tr>
                <th className="text-right px-3 py-2">التاريخ</th><th className="text-right px-3 py-2">القيد</th>
                <th className="text-right px-3 py-2">الحساب</th><th className="text-right px-3 py-2">البيان</th>
                <th className="text-left px-3 py-2">مدين</th><th className="text-left px-3 py-2">دائن</th></tr></thead>
              <tbody>
                {ledgerLines.map((r, i) => (
                  <tr key={`${r.entry_id ?? 'open'}-${r.account}-${i}`} className={`border-t border-gray-100 ${r.opening ? 'bg-gray-50 text-gray-600' : ''}`}>
                    <td className="px-3 py-1.5">{r.date}</td>
                    <td className="px-3 py-1.5 font-mono">
                      {r.entry_id ? <Link className="text-blue-700 hover:underline" to={`/finance/journal?status=&entry=${r.entry_id}`}>{r.number || `#${r.entry_id}`}</Link> : '—'}
                    </td>
                    <td className="px-3 py-1.5 font-mono">{r.account}</td>
                    <td className="px-3 py-1.5">{r.description}</td>
                    <td className={num} dir="ltr">{money(r.debit, { blankZero: true })}</td>
                    <td className={num} dir="ltr">{money(r.credit, { blankZero: true })}</td>
                  </tr>
                ))}
                {!ledgerLines.length && <tr><td colSpan={6} className="px-3 py-4 text-center text-gray-400">لا سطور في الدفتر</td></tr>}
              </tbody>
            </table>
          </DetailTable>

          <DetailTable title="سطور سوفتيك">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs"><tr>
                <th className="text-right px-3 py-2">التاريخ</th><th className="text-right px-3 py-2">الفرع</th>
                <th className="text-right px-3 py-2">البيان</th><th className="text-left px-3 py-2">المبلغ</th></tr></thead>
              <tbody>
                {softech.map((r, i) => (
                  <tr key={i} className="border-t border-gray-100">
                    <td className="px-3 py-1.5">{r.date}</td>
                    <td className="px-3 py-1.5">{r.branch_code ? bl(r.branch_code) : '—'}</td>
                    <td className="px-3 py-1.5">{softechWhat(r)}</td>
                    <td className={num} dir="ltr">{money(r.amount)}</td>
                  </tr>
                ))}
                {!softech.length && <tr><td colSpan={4} className="px-3 py-4 text-center text-gray-400">لا سطور في سوفتيك</td></tr>}
              </tbody>
            </table>
          </DetailTable>
        </div>
      )}
    </div>
  )
}

// ── checks editor (ledger.edit) ──────────────────────────────────────────────

const listText = (v) => (v || []).join('، ')
const parseList = (s) => s.split(/[,،\n]/).map(x => x.trim()).filter(Boolean)

function CheckRow({ check, onSaved }) {
  const [f, setF] = useState(() => ({ tolerance: check.tolerance, accounts: listText(check.account_codes), groups: listText(check.group_names),
    blocks_close: check.blocks_close, is_active: check.is_active }))
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const save = useMutation({
    mutationFn: () => glApi.compareCheckSave({ key: check.key, tolerance: f.tolerance, account_codes: parseList(f.accounts),
      group_names: parseList(f.groups), blocks_close: f.blocks_close, is_active: f.is_active }).then(r => r.data),
    onSuccess: (d) => {
      setErr('')
      const moved = JSON.stringify(d.account_codes) !== JSON.stringify(check.account_codes) || JSON.stringify(d.group_names) !== JSON.stringify(check.group_names)
        || d.is_active !== check.is_active
      setMsg(moved ? 'اتحفظ — اضغط «تحديث الآن» لإعادة الحساب' : 'اتحفظ')
      onSaved()
    },
    onError: (e) => { setMsg(''); setErr(errOf(e, 'تعذّر الحفظ')) },
  })
  const set = (patch) => { setF(x => ({ ...x, ...patch })); setMsg('') }
  return (
    <tr className="border-t border-gray-100 align-top">
      <td className="px-3 py-2 text-sm font-medium">{check.label}<div className="text-[11px] text-gray-400 font-mono">{check.key}</div></td>
      <td className="px-2 py-2"><input className={`${inputCls} w-24`} dir="ltr" value={f.tolerance} onChange={e => set({ tolerance: e.target.value })} /></td>
      <td className="px-2 py-2"><input className={`${inputCls} w-40`} dir="ltr" value={f.accounts} onChange={e => set({ accounts: e.target.value })} /></td>
      <td className="px-2 py-2"><input className={`${inputCls} w-40`} value={f.groups} onChange={e => set({ groups: e.target.value })} /></td>
      <td className="px-2 py-2 text-center"><input type="checkbox" checked={f.blocks_close} onChange={e => set({ blocks_close: e.target.checked })} /></td>
      <td className="px-2 py-2 text-center"><input type="checkbox" checked={f.is_active} onChange={e => set({ is_active: e.target.checked })} /></td>
      <td className="px-2 py-2">
        <button type="button" className={btnPlain} disabled={save.isPending} onClick={() => save.mutate()}>حفظ</button>
        {msg && <div className="text-xs text-green-700 mt-1">{msg}</div>}
        {err && <div className="text-xs text-red-600 mt-1">{err}</div>}
      </td>
    </tr>
  )
}

function ChecksEditor({ onSaved }) {
  const q = useQuery({ queryKey: ['gl', 'compare-checks'], queryFn: () => glApi.compareChecks().then(r => r.data) })
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <ErrorBox>{q.isError ? errOf(q.error, 'تعذّر تحميل الفحوصات') : ''}</ErrorBox>
      {q.isLoading ? <SkeletonTable rows={4} cols={6} /> : (
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs"><tr>
            <th className="text-right px-3 py-2">الفحص</th><th className="text-right px-2 py-2">التسامح</th>
            <th className="text-right px-2 py-2">أكواد الحسابات</th><th className="text-right px-2 py-2">مجموعات الحسابات</th>
            <th className="px-2 py-2">يمنع الإقفال</th><th className="px-2 py-2">مفعّل</th><th /></tr></thead>
          <tbody>{(q.data || []).map(c => <CheckRow key={c.key} check={c} onSaved={onSaved} />)}</tbody>
        </table>
      )}
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────

export default function SoftechComparePage() {
  const qc = useQueryClient()
  const perms = usePermissions('ledger')
  const [params, setParams] = useSearchParams()
  const setParam = (k, v) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); setParams(p, { replace: true }) }
  const periodId = Number(params.get('period')) || null
  const checkKey = params.get('check') || ''
  const onlyUnexplained = params.get('unexplained') === '1'

  const thisYear = new Date().getFullYear()
  const firstYear = Number(OPENING_DATE.slice(0, 4))
  const years = useMemo(() => Array.from({ length: Math.max(1, thisYear - firstYear + 1) }, (_, i) => firstYear + i), [thisYear, firstYear])
  const [year, setYear] = useState(thisYear)
  const periodsQ = useQuery({ queryKey: ['gl', 'periods', year], queryFn: () => glApi.periods(year).then(r => r.data) })
  const periods = useMemo(() => periodsQ.data || [], [periodsQ.data])

  // a linked period may belong to another year: find its year once, from the id's own record
  const linkedQ = useQuery({
    queryKey: ['gl', 'period', periodId], queryFn: () => glApi.period(periodId).then(r => r.data),
    enabled: !!periodId, staleTime: 60000,
  })
  useEffect(() => { if (linkedQ.data?.year) setYear(linkedQ.data.year) }, [linkedQ.data?.year])
  useEffect(() => {
    if (periodId || !periods.length) return
    setParam('period', String((periods.find(p => p.status === 'open') || periods[periods.length - 1]).id))
  }, [periods, periodId]) // eslint-disable-line react-hooks/exhaustive-deps

  const [pending, setPending] = useState(null)   // {since, baseline}: a refresh we asked for, until its run shows up
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const [showChecks, setShowChecks] = useState(false)
  const [openLine, setOpenLine] = useState(null)

  const cmpQ = useQuery({
    queryKey: ['gl', 'compare', periodId],
    queryFn: () => glApi.compare(periodId).then(r => r.data),
    enabled: !!periodId,
    refetchInterval: (q) => (pending || q.state.data?.refresh?.running ? POLL_MS : false),
  })
  const refresh = cmpQ.data?.refresh
  const lastAt = refresh?.last_run?.at || null
  const running = !!refresh?.running || !!pending

  // our run is over once the stored last-run changes; stop waiting after a while whatever happens
  useEffect(() => {
    if (!pending) return undefined
    if (!refresh?.running && lastAt !== pending.baseline) {
      setPending(null)
      qc.invalidateQueries({ queryKey: ['data-freshness'] })
      return undefined
    }
    const t = setTimeout(() => setPending(null), Math.max(0, pending.since + GIVE_UP_MS - Date.now()))
    return () => clearTimeout(t)
  }, [pending, refresh?.running, lastAt, qc])

  const start = useMutation({
    mutationFn: () => glApi.compareRefresh(periodId).then(r => r.data),
    onSuccess: () => { setErr(''); setNote(''); setPending({ since: Date.now(), baseline: lastAt }) },
    onError: (e) => {
      if (e?.response?.data?.code === 'compare_running') { setErr(''); setNote('فيه تحديث شغال دلوقتي، استنى لما يخلص.'); setPending({ since: Date.now(), baseline: lastAt }) }
      else setErr(errOf(e, 'تعذّر بدء التحديث'))
    },
  })
  const refreshNow = async () => { if (periodId && !running) await start.mutateAsync().catch(() => {}) }

  const lines = useMemo(() => cmpQ.data?.lines || [], [cmpQ.data])
  const checks = useMemo(() => {
    const seen = new Map()
    lines.forEach(l => seen.set(l.check_key, l.check_label))
    return [...seen]
  }, [lines])
  const shown = useMemo(() => lines.filter(l => (!checkKey || l.check_key === checkKey) && (!onlyUnexplained || l.needs_explanation)), [lines, checkKey, onlyUnexplained])
  const { sorted, headerProps } = useSortableRows(shown, { getValue, persistKey: 'gl-softech-compare' })
  const unexplained = lines.filter(l => l.needs_explanation).length
  const period = cmpQ.data?.period
  const failed = refresh?.last_run && !refresh.last_run.ok

  const afterExplain = () => qc.invalidateQueries({ queryKey: ['gl', 'compare', periodId] })

  return (
    <div className="space-y-3" dir="rtl">
      <div data-tour="finance-gl-compare-refresh">
        <DataFreshnessBar domains={['gl_compare']} canEdit={!!perms.view} onRefresh={refreshNow} />
        {running && <ProgressBar label="مقارنة الدفتر بسوفتيك" message="بيقرأ من سوفتيك ويحسب الفروق…" since={pending?.since ?? Date.now()} />}
        {note && <div className="text-sm text-amber-700">{note}</div>}
        {failed && !running && (
          <ErrorBox>آخر تحديث ({String(refresh.last_run.at).slice(0, 16).replace('T', ' ')}) ما خلصش{refresh.last_run.detail ? `: ${refresh.last_run.detail}` : ''}</ErrorBox>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select className={inputCls} value={year} onChange={e => { setYear(Number(e.target.value)); setParam('period', '') }} title="السنة">
          {years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        <select className={inputCls} value={periodId || ''} onChange={e => { setParam('period', e.target.value); setOpenLine(null) }} title="الشهر">
          {periods.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
          {periodId && !periods.some(p => p.id === periodId) && <option value={periodId}>{period?.label || '…'}</option>}
        </select>
        <select className={inputCls} value={checkKey} onChange={e => setParam('check', e.target.value)} title="الفحص">
          <option value="">كل الفحوصات</option>
          {checks.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-gray-700">
          <input type="checkbox" checked={onlyUnexplained} onChange={e => setParam('unexplained', e.target.checked ? '1' : '')} />
          اللي محتاج تفسير بس{unexplained > 0 && <span className="rounded-full bg-red-500 text-white text-[11px] px-1.5">{unexplained}</span>}
        </label>
        {perms.edit && (
          <button type="button" className={`${btnPlain} ms-auto`} onClick={() => setShowChecks(s => !s)}>⚙️ إعدادات الفحوصات</button>
        )}
      </div>
      <ErrorBox>{err || (cmpQ.isError ? errOf(cmpQ.error, 'تعذّر تحميل المقارنة') : '')}</ErrorBox>
      {cmpQ.data?.stale && !running && (
        <div className="text-sm rounded-lg border border-amber-200 bg-amber-50 text-amber-800 px-3 py-2">
          الأرقام دي محتاجة تحديث (حصل تغيير في القيود أو الفحوصات بعد آخر حساب). اضغط «تحديث الآن».
        </div>
      )}

      {showChecks && perms.edit && <ChecksEditor onSaved={afterExplain} />}

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="finance-gl-compare-grid">
        {cmpQ.isLoading ? <SkeletonTable rows={8} cols={6} /> : cmpQ.isError ? null : !sorted.length ? (
          <EmptyState title={lines.length ? 'لا فروق مطابقة للتصفية' : 'لا مقارنة لهذا الشهر'}
                      sub={lines.length ? '' : 'اضغط «تحديث الآن» لحسابها من سوفتيك'} />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...headerProps('check_label')} className="text-right px-3 py-2">الفحص</SortTh>
                <SortTh {...headerProps('who')} className="text-right px-3 py-2">الفرع / المورد</SortTh>
                <SortTh {...headerProps('ledger_amount', 'number')} className="text-left px-3 py-2">الدفتر</SortTh>
                <SortTh {...headerProps('softech_amount', 'number')} className="text-left px-3 py-2">سوفتيك</SortTh>
                <SortTh {...headerProps('difference', 'number')} className="text-left px-3 py-2">الفرق</SortTh>
                <SortTh {...headerProps('state', 'number')} className="text-right px-3 py-2">الحالة</SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.map(l => (
                <tr key={l.id} onClick={() => setOpenLine(l.id)}
                    className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${l.needs_explanation ? 'bg-red-50/60' : ''} ${openLine === l.id ? 'outline outline-1 outline-blue-300' : ''}`}>
                  <td className="px-3 py-1.5">{l.check_label}</td>
                  <td className="px-3 py-1.5">{whoOf(l)}</td>
                  <td className={num} dir="ltr">{money(l.ledger_amount)}</td>
                  <td className={num} dir="ltr">{money(l.softech_amount)}</td>
                  <td className={`${num} ${l.needs_explanation ? 'text-red-700 font-bold' : Number(l.difference) !== 0 ? 'text-gray-700' : 'text-gray-400'}`} dir="ltr">{money(l.difference)}</td>
                  <td className="px-3 py-1.5 text-xs">
                    {l.needs_explanation ? <span className="text-red-700">يحتاج تفسير</span>
                      : l.explanation ? <span className="text-green-700" title={l.explanation}>✓ مفسَّر</span>
                      : <span className="text-gray-400">مطابق</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {cmpQ.data && <div className="text-xs text-gray-400">اضغط على صف لعرض تفاصيله وتفسير الفرق.</div>}

      {openLine && (
        <ComparePanel key={openLine} lineId={openLine} perms={perms} onClose={() => setOpenLine(null)} onChanged={afterExplain} />
      )}
    </div>
  )
}
