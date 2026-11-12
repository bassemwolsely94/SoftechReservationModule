/**
 * PeriodClosePage.jsx — «إقفال الفترة»
 * Route: /finance/close   (tabs: ?tab=months|stock|cutover)
 *
 * months  : the year's months, the checklist of the selected one, close / reopen — all inline.
 * stock   : closing-stock per store for a month-end, and the store map.
 * cutover : finance's manual journal import (preview → import) and the validation report.
 *
 * The server decides every rule (checklist, who may close, which months reopen together). This page shows
 * what it returns; the buttons are hidden by permission but the server refuses anyway.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import useGridKeyboard, { GRID_KEYS_HINT } from '../../../hooks/useGridKeyboard'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import ProgressBar from '../../../components/ProgressBar'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import {
  OPENING_DATE, money, errOf, saveBlob, useGlBranches, inputCls, btnPrimary, btnPlain, ErrorBox,
} from './glUi'

const TABS = [
  { key: 'months', label: 'الشهور' },
  { key: 'stock', label: 'بضاعة آخر المدة' },
  { key: 'cutover', label: 'الاستيراد والمطابقة' },
]

const PERIOD_STATUS = {
  open:    { label: 'مفتوح',        cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  closing: { label: 'جاري الإقفال', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  closed:  { label: 'مقفول',        cls: 'bg-green-50 text-green-700 border-green-200' },
}

function PeriodPill({ status }) {
  const s = PERIOD_STATUS[status] || { label: status || '—', cls: 'bg-gray-50 text-gray-500 border-gray-200' }
  return <span className={`inline-block px-2 py-0.5 rounded-full border text-xs ${s.cls}`}>{s.label}</span>
}

const dateOf = (iso) => (iso ? String(iso).slice(0, 10) : '')

/** Where each checklist item is fixed. The server's own `link` (drafts filter) wins. */
function itemLink(item, period) {
  if (item.link && item.key === 'no_drafts') {
    const q = new URLSearchParams(Object.entries(item.link).filter(([, v]) => v))
    return { to: `/finance/journal?${q}`, label: 'افتح المسودات' }
  }
  switch (item.key) {
    case 'no_exceptions':
    case 'late_changes': {
      const q = new URLSearchParams(Object.entries({ tab: 'exceptions', ...item.link }).filter(([, v]) => v))
      return { to: `/finance/journal?${q}`, label: 'افتح الاستثناءات' }
    }
    case 'drafting_ran': return { to: '/finance/journal', label: 'افتح القيود' }
    case 'comparison_fresh':
      return { to: `/finance/softech-compare?period=${period.id}`, label: 'افتح المقارنة' }
    case 'comparison_explained':
    case 'suppliers_explained':
      return { to: `/finance/softech-compare?period=${period.id}&unexplained=1`, label: 'افتح المقارنة' }
    case 'stock_snapshot': return { to: `/finance/close?tab=stock&month=${period.id}`, label: 'بضاعة آخر المدة' }
    default: return null
  }
}

/** A failed blob call carries its {code, detail} as a Blob: read it. */
async function blobError(e, fallback) {
  const d = e?.response?.data
  if (d instanceof Blob) {
    try { return JSON.parse(await d.text()).detail || fallback } catch { return fallback }
  }
  return errOf(e, fallback)
}

// ── months ───────────────────────────────────────────────────────────────────

function Checklist({ period, perms, onChanged }) {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const [reason, setReason] = useState('')
  const [reopening, setReopening] = useState(false)

  // polled without reading SOFTECH; the checklist below is NOT polled
  const detailQ = useQuery({
    queryKey: ['gl', 'period', period.id],
    queryFn: () => glApi.period(period.id).then(r => r.data),
    initialData: period,
    refetchInterval: (q) => (q.state.data?.status === 'closing' ? 3000 : false),
  })
  const p = detailQ.data || period
  const closing = p.status === 'closing'

  const checkQ = useQuery({
    queryKey: ['gl', 'period-checklist', period.id],
    queryFn: () => glApi.periodChecklist(period.id).then(r => r.data),
    enabled: p.status === 'open',
    staleTime: Infinity, refetchOnWindowFocus: false, refetchOnReconnect: false,
  })

  // when a close ends (closed, or back to open with a failure), the list and the checklist are stale
  const [wasClosing, setWasClosing] = useState(false)
  useEffect(() => {
    if (closing) setWasClosing(true)
    else if (wasClosing) {
      setWasClosing(false)
      qc.invalidateQueries({ queryKey: ['gl', 'periods'] })
      qc.invalidateQueries({ queryKey: ['gl', 'period-checklist', period.id] })
      onChanged?.()
    }
  }, [closing]) // eslint-disable-line react-hooks/exhaustive-deps

  const close = useMutation({
    mutationFn: () => glApi.periodClose(period.id).then(r => r.data),
    onSuccess: (data) => {
      setErr('')
      qc.setQueryData(['gl', 'period', period.id], data)
      qc.invalidateQueries({ queryKey: ['gl', 'periods'] })
    },
    onError: (e) => {
      setErr(errOf(e, 'تعذّر بدء الإقفال'))
      qc.invalidateQueries({ queryKey: ['gl', 'period', period.id] })
      qc.invalidateQueries({ queryKey: ['gl', 'period-checklist', period.id] })
    },
  })
  const reopen = useMutation({
    mutationFn: () => glApi.periodReopen(period.id, reason.trim()).then(r => r.data),
    onSuccess: () => {
      setErr(''); setReason(''); setReopening(false)
      qc.invalidateQueries({ queryKey: ['gl'] })
      onChanged?.()
    },
    onError: (e) => setErr(errOf(e, 'تعذّرت إعادة الفتح')),
  })

  const checklist = checkQ.data
  const items = useMemo(() => {
    const rank = (i) => (i.ok ? 2 : i.blocking ? 0 : 1)
    return [...(checklist?.items || [])].sort((a, b) => rank(a) - rank(b))
  }, [checklist])
  const stuck = !!p.close_stuck
  const canClose = !!checklist?.can_close && p.status === 'open'
  const failure = p.last_close_failure

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-bold text-gray-900">{p.label}</h2>
        <PeriodPill status={p.status} />
        {p.status === 'closed' && (
          <span className="text-xs text-gray-500">
            أقفله {p.closed_by_name || '—'} · {dateOf(p.closed_at)}
            {p.closing_stock_total != null && <> · بضاعة آخر المدة {money(p.closing_stock_total)}</>}
          </span>
        )}
      </div>

      <ErrorBox>{err}</ErrorBox>
      {failure && p.status === 'open' && (
        <ErrorBox>آخر محاولة إقفال وقفت: {failure.detail}</ErrorBox>
      )}

      {closing && (
        <div className="space-y-2" data-tour="finance-gl-close-action">
          <ProgressBar label={`إقفال ${p.label}`} message="جاري قراءة المخزون من سوفتيك وترحيل قيد الإقفال…"
                       since={p.closing_started_at ? Date.parse(p.closing_started_at) : undefined} />
          {stuck && perms.finalize && (
            <div className="flex items-center gap-3 text-sm">
              <span className="text-amber-700">الإقفال واقف من فترة طويلة.</span>
              <button type="button" className={btnPrimary} disabled={close.isPending} onClick={() => close.mutate()}>إعادة المحاولة</button>
            </div>
          )}
        </div>
      )}

      {p.status === 'open' && (
        <>
          <div className="flex items-center justify-between" data-tour="finance-gl-close-checklist">
            <div className="text-sm font-medium text-gray-700">شروط الإقفال</div>
            <button type="button" className={btnPlain} disabled={checkQ.isFetching}
                    onClick={() => checkQ.refetch()}>{checkQ.isFetching ? 'جارٍ الفحص…' : 'إعادة الفحص'}</button>
          </div>
          {checkQ.isLoading && <ProgressBar label="فحص شروط الإقفال" message="بيقرأ من سوفتيك…" since={Date.now()} />}
          {checkQ.isError && <ErrorBox>{errOf(checkQ.error, 'تعذّر فحص شروط الإقفال')}</ErrorBox>}
          {!!items.length && (
            <ul className="divide-y divide-gray-100 text-sm">
              {items.map(i => {
                const link = !i.ok ? itemLink(i, period) : null
                return (
                  <li key={i.key} className="py-2 flex flex-wrap items-start gap-2">
                    <span className={i.ok ? 'text-green-600' : i.blocking ? 'text-red-600' : 'text-amber-600'}>
                      {i.ok ? '✓' : '✗'}
                    </span>
                    <div className="flex-1 min-w-[12rem]">
                      <span className={i.ok ? 'text-gray-700' : 'text-gray-900 font-medium'}>{i.label_ar}</span>
                      {!i.ok && !i.blocking && <span className="ms-2 text-xs text-amber-700">تنبيه — مش بيمنع الإقفال</span>}
                      {i.detail && <div className="text-xs text-gray-500">{i.detail}</div>}
                    </div>
                    {link && <Link to={link.to} className="text-xs text-green-700 hover:underline">{link.label} ←</Link>}
                  </li>
                )
              })}
            </ul>
          )}
          {perms.finalize && (
            <div className="flex flex-wrap items-center gap-3" data-tour="finance-gl-close-action">
              <button type="button" className={btnPrimary} disabled={!canClose || close.isPending}
                      onClick={() => close.mutate()}>
                {close.isPending ? 'جارٍ البدء…' : 'إقفال الشهر'}
              </button>
              {!canClose && !checkQ.isLoading && <span className="text-xs text-gray-500">الإقفال يتفتح لما كل الشروط المانعة تبقى ✓</span>}
              {p.closes_year && (
                <span className="text-xs text-blue-700">إقفال ديسمبر بيقفل السنة كمان (قيد إقفال الأرباح والخسائر).</span>
              )}
            </div>
          )}
        </>
      )}

      {p.status === 'closed' && perms.finalize && p.can_reopen && (
        <div className="space-y-2" data-tour="finance-gl-close-action">
          {!reopening ? (
            <button type="button" className={btnPlain} onClick={() => setReopening(true)}>إعادة فتح</button>
          ) : (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2 text-sm">
              <div className="text-amber-800">
                {p.reopens_with?.length
                  ? <>إعادة فتح {p.label} هتفتح معاه الشهور اللي بعده: <b>{p.reopens_with.join('، ')}</b>.</>
                  : <>إعادة فتح {p.label} مش هتأثر على شهور تانية.</>}
                {p.closes_year && ' وهتلغي إقفال السنة.'}
              </div>
              <input className={`${inputCls} w-full`} placeholder="سبب إعادة الفتح (مطلوب)" value={reason}
                     maxLength={500} onChange={e => setReason(e.target.value)} />
              <div className="flex gap-2">
                <button type="button" className={btnPrimary} disabled={!reason.trim() || reopen.isPending}
                        onClick={() => reopen.mutate()}>{reopen.isPending ? 'جارٍ إعادة الفتح…' : 'تأكيد إعادة الفتح'}</button>
                <button type="button" className={btnPlain} onClick={() => { setReopening(false); setReason('') }}>إلغاء</button>
              </div>
            </div>
          )}
        </div>
      )}
      {p.status === 'closed' && !p.can_reopen && (
        <div className="text-xs text-gray-500">
          إعادة الفتح متاحة لآخر {Number(p.gl_reopen_window_months).toLocaleString('ar-EG')} شهور مقفولة بس.
        </div>
      )}
    </div>
  )
}

function MonthsTab({ periods, periodsQ, year, setYear, years, selectedId, setSelectedId, perms }) {
  const { sorted, headerProps } = useSortableRows(periods, {
    defaultSort: { key: 'month', dir: 'asc', type: 'number' }, persistKey: 'gl-close-months',
  })
  const selected = periods.find(p => p.id === selectedId)
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm">
        <label className="text-gray-500">السنة</label>
        <select className={inputCls} value={year} onChange={e => setYear(Number(e.target.value))}>
          {years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      <ErrorBox>{periodsQ.isError ? errOf(periodsQ.error, 'تعذّر تحميل الشهور') : ''}</ErrorBox>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="finance-gl-close-months">
        {periodsQ.isLoading ? <SkeletonTable rows={6} cols={5} /> : !sorted.length ? (
          <EmptyState title="لا توجد شهور" sub="السنة دي مفيهاش شهور من تاريخ الافتتاح" />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...headerProps('month', 'number')} className="text-right px-3 py-2">الشهر</SortTh>
                <SortTh {...headerProps('status')} className="text-right px-3 py-2">الحالة</SortTh>
                <SortTh {...headerProps('closed_by_name')} className="text-right px-3 py-2">أقفله</SortTh>
                <SortTh {...headerProps('closed_at', 'date')} className="text-right px-3 py-2">تاريخ الإقفال</SortTh>
                <SortTh {...headerProps('closing_stock_total', 'number')} className="text-left px-3 py-2">بضاعة آخر المدة</SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.map(p => (
                <tr key={p.id} onClick={() => setSelectedId(p.id)}
                    className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${p.id === selectedId ? 'bg-green-50/60' : ''}`}>
                  <td className="px-3 py-1.5 font-medium">{p.label}</td>
                  <td className="px-3 py-1.5"><PeriodPill status={p.status} /></td>
                  <td className="px-3 py-1.5 text-xs text-gray-600">{p.closed_by_name || ''}</td>
                  <td className="px-3 py-1.5 text-xs text-gray-600">{dateOf(p.closed_at)}</td>
                  <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">
                    {p.closing_stock_total == null ? '—' : money(p.closing_stock_total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {selected && <Checklist key={selected.id} period={selected} perms={perms} />}
    </div>
  )
}

// ── stock ────────────────────────────────────────────────────────────────────

function StoresTable({ stores }) {
  const { sorted, headerProps } = useSortableRows(stores, {
    defaultSort: { key: 'value', dir: 'desc', type: 'number' }, persistKey: 'gl-close-stores',
  })
  if (!sorted.length) return <EmptyState title="لا توجد مخازن" sub="لسه مفيش قراءة لبضاعة آخر المدة للشهر ده" />
  return (
    <table className="w-full text-sm">
      <thead className="bg-gray-50 text-gray-600 text-xs">
        <tr>
          <SortTh {...headerProps('store_code')} className="text-right px-3 py-2">المخزن</SortTh>
          <SortTh {...headerProps('store_name')} className="text-right px-3 py-2">الاسم</SortTh>
          <SortTh {...headerProps('branch_label')} className="text-right px-3 py-2">الفرع</SortTh>
          <SortTh {...headerProps('included')} className="text-right px-3 py-2">داخل في البضاعة</SortTh>
          <SortTh {...headerProps('rows', 'number')} className="text-left px-3 py-2">الأصناف</SortTh>
          <SortTh {...headerProps('value', 'number')} className="text-left px-3 py-2">القيمة</SortTh>
          <SortTh {...headerProps('snapshot_date', 'date')} className="text-right px-3 py-2">تاريخ اللقطة</SortTh>
        </tr>
      </thead>
      <tbody>
        {sorted.map(s => (
          <tr key={s.store_code} className={`border-t border-gray-100 ${s.included ? '' : 'text-gray-400'}`}>
            <td className="px-3 py-1.5 font-mono">{s.store_code}</td>
            <td className="px-3 py-1.5">{s.store_name}</td>
            <td className="px-3 py-1.5">{s.branch_label}</td>
            <td className="px-3 py-1.5">{s.included ? 'داخل' : 'مستبعد'}</td>
            <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{s.rows}</td>
            <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(s.value)}</td>
            <td className="px-3 py-1.5 text-xs">
              {dateOf(s.snapshot_date)}{s.carried && <span className="ms-1 text-amber-700">محمول من لقطة سابقة</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function StoreMap({ branches }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['gl', 'closing-stores'], queryFn: () => glApi.closingStockStores().then(r => r.data) })
  const [draft, setDraft] = useState({})   // store_code → {branch?, included?}
  const [err, setErr] = useState('')
  const rows = q.data || []
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: 'gl-close-store-map' })
  const save = useMutation({
    mutationFn: (stores) => glApi.closingStockStoresPatch(stores).then(r => r.data),
    onSuccess: (data, stores) => {
      setErr('')
      qc.setQueryData(['gl', 'closing-stores'], data)
      setDraft(d => { const n = { ...d }; Object.keys(stores).forEach(k => delete n[k]); return n })
    },
    onError: (e) => setErr(errOf(e, 'تعذّر حفظ إعداد المخزن')),
  })
  const patch = (code, p) => setDraft(d => ({ ...d, [code]: { ...d[code], ...p } }))
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      <div className="font-medium text-gray-900">مخازن بضاعة آخر المدة</div>
      <p className="text-xs text-gray-500">لكل مخزن: الفرع اللي بضاعته بتتسجل عليه، وهل بيدخل في بضاعة آخر المدة. التعديل بيسري من أول إقفال بعده.</p>
      <ErrorBox>{err || (q.isError ? errOf(q.error, 'تعذّر تحميل المخازن') : '')}</ErrorBox>
      {q.isLoading ? <SkeletonTable rows={4} cols={4} /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...headerProps('store_code')} className="text-right px-3 py-2">المخزن</SortTh>
                <SortTh {...headerProps('branch_label')} className="text-right px-3 py-2">الفرع</SortTh>
                <SortTh {...headerProps('included')} className="text-right px-3 py-2">داخل</SortTh>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {sorted.map(r => {
                const d = draft[r.store_code] || {}
                const included = d.included ?? r.included
                const branch = d.branch ?? r.branch_code
                const dirty = d.included !== undefined || d.branch !== undefined
                return (
                  <tr key={r.store_code} className="border-t border-gray-100">
                    <td className="px-3 py-1.5 font-mono">{r.store_code}</td>
                    <td className="px-3 py-1.5">
                      <select className={inputCls} value={branch} onChange={e => patch(r.store_code, { branch: e.target.value })}>
                        {!branches.some(b => b.softech_branch_id === r.branch_code) && <option value={r.branch_code}>{r.branch_label}</option>}
                        {branches.map(b => <option key={b.id} value={b.softech_branch_id}>{b.label}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-1.5">
                      <input type="checkbox" checked={!!included} onChange={e => patch(r.store_code, { included: e.target.checked })} />
                    </td>
                    <td className="px-3 py-1.5 text-left whitespace-nowrap">
                      <button type="button" className={btnPrimary} disabled={!dirty || save.isPending}
                              onClick={() => save.mutate({ [r.store_code]: { branch, included } })}>حفظ</button>
                      {r.overridden && (
                        <button type="button" className={`${btnPlain} ms-2`} disabled={save.isPending}
                                onClick={() => save.mutate({ [r.store_code]: null })}>رجوع للافتراضي</button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function StockTab({ periods, selectedId, setSelectedId, perms, branches }) {
  const savedQ = useQuery({
    queryKey: ['gl', 'closing-stock', selectedId],
    queryFn: () => glApi.closingStock(selectedId, false).then(r => r.data),
    enabled: !!selectedId,
  })
  const preview = useMutation({ mutationFn: () => glApi.closingStock(selectedId, true).then(r => r.data) })
  useEffect(() => { preview.reset() }, [selectedId]) // eslint-disable-line react-hooks/exhaustive-deps

  const live = preview.data
  const snap = savedQ.data?.snapshot
  const shown = live || (snap ? { ...snap, stores: savedQ.data.stores } : null)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-sm" data-tour="finance-gl-close-stock">
        <label className="text-gray-500">الشهر</label>
        <select className={inputCls} value={selectedId || ''} onChange={e => setSelectedId(Number(e.target.value))}>
          {periods.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <button type="button" className={btnPlain} disabled={!selectedId || preview.isPending} onClick={() => preview.mutate()}>
          معاينة من سوفتيك
        </button>
        {live ? <span className="text-xs text-blue-700">معاينة حية — لسه مش محفوظة</span>
          : snap ? <span className="text-xs text-gray-500">اللقطة المحفوظة وقت الإقفال ({dateOf(snap.read_at)})</span> : null}
      </div>
      {preview.isPending && <ProgressBar label="قراءة المخزون" message="بيقرأ أرصدة المخازن من سوفتيك…" since={Date.now()} />}
      <ErrorBox>{preview.isError ? errOf(preview.error, 'تعذّرت القراءة من سوفتيك') : ''}</ErrorBox>
      <ErrorBox>{savedQ.isError ? errOf(savedQ.error, 'تعذّر تحميل اللقطة') : ''}</ErrorBox>
      {shown && (
        <>
          <div className="flex flex-wrap gap-6 text-sm">
            <div>الإجمالي: <b className="font-mono" dir="ltr">{money(shown.total)}</b></div>
            <div>المستبعد: <span className="font-mono" dir="ltr">{money(shown.excluded_total)}</span></div>
          </div>
          {!!shown.missing_stores?.length && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2">
              مخازن ناقصة لقطتها لتاريخ آخر الشهر: {shown.missing_stores.map(m => `${m.store_code} (${m.branch_label})`).join('، ')}
            </div>
          )}
          <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <StoresTable stores={shown.stores || []} />
          </div>
        </>
      )}
      {!shown && !savedQ.isLoading && !preview.isPending && (
        <EmptyState title="لا توجد لقطة محفوظة" sub="اضغط «معاينة من سوفتيك» لقراءة بضاعة آخر الشهر" />
      )}
      {perms.edit && <StoreMap branches={branches} />}
    </div>
  )
}

// ── cutover ──────────────────────────────────────────────────────────────────

const IMPORT_STATUS = {
  manual:               'يدوي — هيتستورد',
  softech:              'من سوفتيك — بيتخطى',
  mixed:                'مختلط (يدوي + سوفتيك)',
  unbalanced:           'غير متوازن',
  unknown_account:      'حساب غير موجود',
  unknown_branch:       'فرع غير معروف',
  before_opening:       'قبل تاريخ الافتتاح',
  changed_since_import: 'اتغيّر من آخر استيراد',
  possible_duplicate:   'تكرار محتمل',
  closed_period:        'شهره مقفول — مش هيتستورد',
}
const STATUS_ORDER = ['manual', 'mixed', 'possible_duplicate', 'unbalanced', 'unknown_account', 'unknown_branch',
  'before_opening', 'closed_period', 'changed_since_import', 'softech']
const SELECTABLE = ['mixed', 'possible_duplicate']
const SHOW_LIMIT = 200
const BOOK_CHOICES = [['cash', 'نقدية'], ['credit', 'آجل']]

function GroupTable({ rows, selectable, selected, setSelected, labelOf }) {
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: 'gl-close-import-groups' })
  const shown = useMemo(() => sorted.slice(0, SHOW_LIMIT), [sorted])
  const toggle = (r) => setSelected(s => { const n = new Set(s); n.has(r.key) ? n.delete(r.key) : n.add(r.key); return n })
  const kb = useGridKeyboard({
    rows: shown, getKey: r => r.key,
    onToggle: selectable ? toggle : undefined,
    onSelectAll: selectable ? () => setSelected(s => {
      const all = shown.every(r => s.has(r.key))
      const n = new Set(s)
      shown.forEach(r => (all ? n.delete(r.key) : n.add(r.key)))
      return n
    }) : undefined,
  })
  return (
    <div className="overflow-x-auto" {...kb.containerProps}>
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-gray-600 text-xs">
          <tr>
            {selectable && <th className="px-2 py-2 w-8" />}
            <SortTh {...headerProps('date', 'date')} className="text-right px-3 py-2">التاريخ</SortTh>
            <SortTh {...headerProps('book')} className="text-right px-3 py-2">الدفتر</SortTh>
            <SortTh {...headerProps('branch')} className="text-right px-3 py-2">الفرع</SortTh>
            <SortTh {...headerProps('description')} className="text-right px-3 py-2">البيان</SortTh>
            <SortTh {...headerProps('lines', 'number')} className="text-left px-3 py-2">الأسطر</SortTh>
            <SortTh {...headerProps('debit', 'number')} className="text-left px-3 py-2">مدين</SortTh>
            <SortTh {...headerProps('credit', 'number')} className="text-left px-3 py-2">دائن</SortTh>
            <th className="text-right px-3 py-2">الحسابات</th>
          </tr>
        </thead>
        <tbody>
          {shown.map(r => {
            const kbp = kb.rowProps(r)
            return (
              <tr key={r.key} {...kbp} className={`border-t border-gray-100 ${selected?.has(r.key) ? 'bg-green-50/60' : ''} ${kbp.className}`}>
                {selectable && (
                  <td className="px-2 py-1.5">
                    <input type="checkbox" checked={!!selected?.has(r.key)} onChange={() => toggle(r)} />
                  </td>
                )}
                <td className="px-3 py-1.5">{r.date}</td>
                <td className="px-3 py-1.5">{r.book}</td>
                <td className="px-3 py-1.5">{(r.branch_id != null && labelOf(r.branch_id)) || r.branch || '—'}</td>
                <td className="px-3 py-1.5">
                  {r.description}
                  {r.existing_entry_number && <div className="text-xs text-gray-500">قيد موجود: {r.existing_entry_number}</div>}
                </td>
                <td className="px-3 py-1.5 text-left font-mono" dir="ltr">{r.lines}</td>
                <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(r.debit)}</td>
                <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(r.credit)}</td>
                <td className="px-3 py-1.5 text-xs font-mono">{(r.accounts || []).join(' ')}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {rows.length > SHOW_LIMIT && (
        <div className="px-3 py-2 text-xs text-gray-500">بيظهر أول {SHOW_LIMIT} من {rows.length} (رتّب لتغيير الترتيب).</div>
      )}
      {selectable && <div className="px-3 py-2 text-xs text-gray-400">{GRID_KEYS_HINT}</div>}
    </div>
  )
}

const RESULT_LABELS = [
  ['imported', 'اتعمل مسودات'], ['included', 'مختلط اتضم'], ['already_imported', 'مستورد قبل كده'],
  ['parked', 'اتعلّق للمراجعة'], ['parked_existing', 'معلّق من قبل'], ['softech', 'من سوفتيك (اتخطى)'],
]

function ImportSection({ perms }) {
  const qc = useQueryClient()
  const { labelOf } = useGlBranches()
  const [file, setFile] = useState(null)
  const [book, setBook] = useState('')
  const [needBook, setNeedBook] = useState(false)
  const [preview, setPreview] = useState(null)
  const [selected, setSelected] = useState(() => new Set())
  const [result, setResult] = useState(null)
  const [err, setErr] = useState('')

  const fail = (e) => {
    const code = e?.response?.data?.code
    if (code === 'book_required') setNeedBook(true)
    setErr(errOf(e, 'تعذّر قراءة الملف'))
  }
  const doPreview = useMutation({
    mutationFn: () => glApi.manualImportPreview(file, book).then(r => r.data),
    onSuccess: (d) => { setErr(''); setPreview(d); setResult(null); setSelected(new Set()) },
    onError: fail,
  })
  const doImport = useMutation({
    mutationFn: () => glApi.manualImport(file, book, [...selected]).then(r => r.data),
    onSuccess: (d) => {
      setErr(''); setResult(d); setPreview(null); setSelected(new Set())
      qc.invalidateQueries({ queryKey: ['gl'] })
    },
    onError: fail,
  })

  const byStatus = useMemo(() => {
    const m = {}
    ;(preview?.groups || []).forEach(g => { (m[g.status] ||= []).push(g) })
    return m
  }, [preview])
  const netLinks = (preview?.link_accounts || []).filter(l => Number(l.net) !== 0)
  const importable = (preview?.counts?.manual || 0) + selected.size
  // a mixed group nobody ticked is parked by the import: a file of only those still has work to do
  const toPark = (byStatus.mixed || []).filter(g => !selected.has(g.key)).length
  const onFile = (f) => { setFile(f); setPreview(null); setResult(null); setErr(''); setNeedBook(false) }

  return (
    <section className="bg-white rounded-xl border border-gray-200 p-4 space-y-3" data-tour="finance-gl-cutover-import">
      <h2 className="font-bold text-gray-900">استيراد قيود المالية اليدوية</h2>
      {!file && !preview && !result && (
        <p className="text-sm text-gray-600">المطلوب هنا هو دفتر يومية المالية لسنة 2026 (ملف Excel). لحد ما يترفع، مفيش حاجة تانية بتتعمل.</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input type="file" accept=".xlsx" className="text-sm"
               onChange={e => onFile(e.target.files?.[0] || null)} />
        {needBook && (
          <label className="flex items-center gap-1 text-sm">
            <span className="text-gray-600">الدفتر</span>
            <select className={inputCls} value={book} onChange={e => setBook(e.target.value)}>
              <option value="">اختر…</option>
              {BOOK_CHOICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        )}
        <button type="button" className={btnPlain} disabled={!file || (needBook && !book) || doPreview.isPending}
                onClick={() => doPreview.mutate()}>معاينة</button>
      </div>
      {doPreview.isPending && <ProgressBar label="قراءة الملف" message="بيحلل الأسطر ويجمّعها في قيود…" since={Date.now()} />}
      <ErrorBox>{err}</ErrorBox>

      {preview && (
        <div className="space-y-4">
          {!!preview.manual_accounts?.length && (
            <div>
              <div className="text-sm font-medium text-gray-700 mb-1">الحسابات اليدوية (مش بتتغذى من سوفتيك)</div>
              <div className="flex flex-wrap gap-2 text-xs">
                {preview.manual_accounts.map(a => (
                  <span key={a.code} className="px-2 py-0.5 rounded-full border border-gray-200 bg-gray-50">
                    <span className="font-mono">{a.code}</span> {a.name}
                  </span>
                ))}
              </div>
            </div>
          )}
          {(preview.warnings || []).map((w, i) => (
            <div key={i} className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2">{w}</div>
          ))}
          {netLinks.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2">
              حسابات الوسيط اللي صافيها مش صفر: {netLinks.map(l => `${l.code} (${money(l.net)})`).join('، ')}
            </div>
          )}
          {preview.party_missing > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm px-3 py-2">
              {preview.party_missing} سطر من غير كود طرف على حساب بيطلبه: الاعتماد هيرفضه لحد ما يتكمل.
            </div>
          )}
          <div className="flex flex-wrap gap-2 text-xs">
            {STATUS_ORDER.filter(s => preview.counts?.[s]).map(s => (
              <span key={s} className="px-2 py-0.5 rounded-full border border-gray-200 bg-gray-50">
                {IMPORT_STATUS[s]}: <b>{preview.counts[s]}</b>
              </span>
            ))}
            <span className="text-gray-500">· {preview.totals?.rows} سطر في {preview.totals?.groups} قيد</span>
          </div>

          {STATUS_ORDER.filter(s => byStatus[s]?.length).map(s => (
            <details key={s} open={s !== 'softech'} className="border border-gray-200 rounded-lg">
              <summary className="px-3 py-2 text-sm cursor-pointer select-none">
                {IMPORT_STATUS[s]} <b>({byStatus[s].length})</b>
                {SELECTABLE.includes(s) && <span className="ms-2 text-xs text-gray-500">حدد اللي عايز تضمّه للاستيراد</span>}
              </summary>
              {s === 'softech' && !!preview.softech_summary?.length && (
                <div className="px-3 pb-2 text-xs text-gray-600 space-y-0.5">
                  {preview.softech_summary.map((r, i) => (
                    <div key={i}>
                      <span className="font-mono">{r.accounts.join(' ')}</span> — {r.groups} قيد · مدين {money(r.debit)} · دائن {money(r.credit)}
                    </div>
                  ))}
                </div>
              )}
              <GroupTable rows={byStatus[s]} selectable={SELECTABLE.includes(s)} selected={selected}
                          setSelected={setSelected} labelOf={labelOf} />
            </details>
          ))}

          {perms.create && (
            <div className="flex items-center gap-3">
              <button type="button" className={btnPrimary} disabled={(!importable && !toPark) || doImport.isPending}
                      onClick={() => doImport.mutate()}>
                {doImport.isPending ? 'جارٍ الاستيراد…' : `استيراد (${importable})`}
              </button>
              <span className="text-xs text-gray-500">
                بيتعمل مسودات بس، والاعتماد من القيود. الاستيراد مرتين مبيكررش.
                {toPark > 0 && ` ${toPark} مختلط مش متحدد هيتعلّق في الاستثناءات لحد قرار المحاسب.`}
              </span>
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="space-y-2 text-sm">
          <div className="rounded-lg border border-green-200 bg-green-50 text-green-800 px-3 py-2">
            تم الاستيراد — {RESULT_LABELS.filter(([k]) => result[k]).map(([k, l]) => `${l}: ${result[k]}`).join(' · ') || 'مفيش جديد'}
          </div>
          {(Array.isArray(result.failed) ? result.failed.length : result.failed) > 0 && (
            <ErrorBox>
              {Array.isArray(result.failed) ? result.failed.length : result.failed} قيد اترفض أثناء الحفظ.
              {Array.isArray(result.failed) && (
                <ul className="mt-1 text-xs font-mono" dir="ltr">
                  {result.failed.map(f => <li key={f.key}>{f.key}: {f.code}</li>)}
                </ul>
              )}
            </ErrorBox>
          )}
          {!!result.include_unmatched?.length && (
            <div className="text-amber-700">{result.include_unmatched.length} اختيار مطابقش أي قيد مختلط في الملف.</div>
          )}
          {result.party_missing > 0 && (
            <div className="text-amber-700">{result.party_missing} سطر من غير كود طرف، الاعتماد هيرفضه لحد ما يتكمل.</div>
          )}
        </div>
      )}
    </section>
  )
}

function ValidateSection({ perms }) {
  const [file, setFile] = useState(null)
  const [through, setThrough] = useState('')
  const [summary, setSummary] = useState(null)
  const [err, setErr] = useState('')
  const run = useMutation({
    mutationFn: () => glApi.validation(file, through),
    onSuccess: async (res) => {
      setErr('')
      const h = res.headers || {}
      setSummary({ differences: h['x-gl-validation-differences'], total: h['x-gl-validation-difference-total'] })
      await saveBlob(Promise.resolve(res), `gl_validation_${through || 'report'}.xlsx`)
    },
    onError: async (e) => setErr(await blobError(e, 'تعذّرت المطابقة')),
  })
  return (
    <section className="bg-white rounded-xl border border-gray-200 p-4 space-y-3" data-tour="finance-gl-cutover-validate">
      <h2 className="font-bold text-gray-900">مطابقة دفاتر المالية مع الدفتر العام</h2>
      <p className="text-sm text-gray-600">ارفع ملف المالية، وهتنزّل تقرير بالفروق بينه وبين الدفتر العام عندنا.</p>
      <div className="flex flex-wrap items-center gap-2">
        <input type="file" accept=".xlsx" className="text-sm" onChange={e => { setFile(e.target.files?.[0] || null); setSummary(null); setErr('') }} />
        <label className="flex items-center gap-1 text-sm text-gray-600">حتى تاريخ
          <input type="date" className={inputCls} value={through} min={OPENING_DATE} onChange={e => setThrough(e.target.value)} />
        </label>
        {perms.export && (
          <button type="button" className={btnPrimary} disabled={!file || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? 'جارٍ المطابقة…' : 'مطابقة وتنزيل التقرير'}
          </button>
        )}
      </div>
      {run.isPending && <ProgressBar label="المطابقة" message="بيقارن الملف بالدفتر…" since={Date.now()} />}
      <ErrorBox>{err}</ErrorBox>
      {summary && (
        <div className="text-sm rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
          عدد الفروق: <b>{summary.differences ?? '—'}</b> · إجمالي الفروق في التقرير: <b className="font-mono" dir="ltr">{money(summary.total)}</b>
          <div className="text-xs text-gray-500 mt-1">الفرق اللي بيظهر في أكتر من عرض بيتحسب في الإجمالي مرتين. التفاصيل في الملف.</div>
        </div>
      )}
    </section>
  )
}

function CutoverTab({ perms }) {
  return (
    <div className="space-y-4">
      {(perms.create || perms.edit) && <ImportSection perms={perms} />}
      {perms.export && <ValidateSection perms={perms} />}
      {!perms.create && !perms.edit && !perms.export && (
        <EmptyState title="غير متاح" sub="الاستيراد والمطابقة محتاجين صلاحية الإنشاء أو التصدير" />
      )}
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────

export default function PeriodClosePage() {
  const perms = usePermissions('ledger')
  const [params, setParams] = useSearchParams()
  const tab = TABS.some(t => t.key === params.get('tab')) ? params.get('tab') : 'months'
  useHelpTab(tab)
  const setTab = (t) => { const p = new URLSearchParams(params); p.set('tab', t); setParams(p, { replace: true }) }

  const thisYear = new Date().getFullYear()
  const firstYear = Number(OPENING_DATE.slice(0, 4))
  const years = useMemo(() => Array.from({ length: Math.max(1, thisYear - firstYear + 1) }, (_, i) => firstYear + i), [thisYear, firstYear])
  const [year, setYear] = useState(Math.min(Math.max(thisYear, firstYear), thisYear))
  const [selectedId, setSelectedId] = useState(() => Number(params.get('month')) || null)
  const { branches: rawBranches, labelOf } = useGlBranches()
  const branches = useMemo(() => rawBranches.map(b => ({ ...b, label: labelOf(b.id) })), [rawBranches]) // eslint-disable-line react-hooks/exhaustive-deps

  const periodsQ = useQuery({
    queryKey: ['gl', 'periods', year],
    queryFn: () => glApi.periods(year).then(r => r.data),
  })
  const periods = useMemo(() => periodsQ.data || [], [periodsQ.data])
  useEffect(() => {
    if (!periods.length || periods.some(p => p.id === selectedId)) return
    const first = periods.find(p => p.status !== 'closed') || periods[periods.length - 1]
    setSelectedId(first.id)
  }, [periods, selectedId])

  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex gap-1 border-b border-gray-200">
        {TABS.map(t => (
          <button key={t.key} type="button" onClick={() => setTab(t.key)}
                  className={`px-4 py-2 text-sm border-b-2 -mb-px ${tab === t.key ? 'border-green-600 text-green-700 font-medium' : 'border-transparent text-gray-600 hover:text-gray-900'}`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'months' && (
        <MonthsTab periods={periods} periodsQ={periodsQ} year={year} setYear={setYear} years={years}
                   selectedId={selectedId} setSelectedId={setSelectedId} perms={perms} />
      )}
      {tab === 'stock' && (
        <StockTab periods={periods} selectedId={selectedId} setSelectedId={setSelectedId} perms={perms} branches={branches} />
      )}
      {tab === 'cutover' && <CutoverTab perms={perms} />}
    </div>
  )
}
