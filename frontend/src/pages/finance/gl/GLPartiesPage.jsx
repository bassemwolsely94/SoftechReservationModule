/**
 * GLPartiesPage.jsx — «الأطراف»
 * Route: /finance/parties
 *
 * Finance's own supplier / customer codes ↔ SOFTECH persons. The server proposes matches by name;
 * a person confirms each one (Enter) or picks another SOFTECH person (M). Unconfirmed parties turn
 * their documents into exceptions, so this is the gate before drafting. Confirm / reject need
 * ledger.approve, import / propose need ledger.edit — the server enforces both.
 */
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import useGridKeyboard, { GRID_KEYS_HINT } from '../../../hooks/useGridKeyboard'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import { errOf, listOf, inputCls, btnPrimary, btnPlain, ErrorBox } from './glUi'

export const PARTY_TYPES = { supplier: 'مورد', customer: 'عميل', employee: 'موظف', partner: 'شريك', other: 'أخرى' }
const STATUSES = { unmapped: 'غير مربوط', proposed: 'مقترح', confirmed: 'مؤكد', rejected: 'مرفوض' }
const BASIS = { exact: 'تطابق تام', tokens: 'تطابق كلمات', manual: 'يدوي' }
const STATUS_CLS = {
  unmapped: 'bg-gray-100 text-gray-600 border-gray-200',
  proposed: 'bg-amber-50 text-amber-700 border-amber-200',
  confirmed: 'bg-green-50 text-green-700 border-green-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
}

function useDebounced(v, ms = 300) {
  const [d, setD] = useState(v)
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms])
  return d
}

// ── pick another SOFTECH person (search on the A/P party mirror) ─────────────
function PersonPicker({ party, onPick, onClose, busy }) {
  const [q, setQ] = useState(party.name || '')
  const dq = useDebounced(q)
  const ref = useRef(null)
  useEffect(() => { ref.current?.focus(); ref.current?.select() }, [])
  const res = useQuery({
    queryKey: ['gl', 'recon-parties', party.party_type, dq],
    queryFn: () => glApi.partyPersons({ q: dq || undefined, type: party.party_type })
      .then(r => listOf(r.data)),
    enabled: dq.trim().length >= 2,
  })
  return (
    <div className="bg-green-50/40 border border-green-200 rounded-lg p-2 space-y-1.5">
      <div className="flex items-center gap-2">
        <input ref={ref} className={`${inputCls} flex-1`} value={q} placeholder="ابحث باسم أو كود الشخص في SOFTECH (* للبدل)"
               onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Escape') onClose() }} />
        <button type="button" className={btnPlain} onClick={onClose}>إغلاق</button>
      </div>
      {res.isError && <div className="text-xs text-red-600">{errOf(res.error, 'تعذّر البحث')}</div>}
      {res.isLoading && <div className="text-xs text-gray-500">جاري البحث…</div>}
      {res.data && res.data.length === 0 && <div className="text-xs text-gray-500">لا يوجد شخص مطابق</div>}
      <div className="grid gap-1 sm:grid-cols-2">
        {(res.data || []).map(p => (
          <button key={p.id} type="button" disabled={busy} onClick={() => onPick(p.softech_personcode)}
                  className="text-right bg-white border border-gray-200 rounded-lg px-2 py-1 text-sm hover:bg-green-50 disabled:opacity-50">
            <span className="font-mono text-gray-500">{p.softech_personcode}</span> · {p.name}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── import + propose bar (ledger.edit) ───────────────────────────────────────
function ImportBar({ onDone }) {
  const fileRef = useRef(null)
  const [file, setFile] = useState(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const imp = useMutation({
    mutationFn: () => glApi.partiesImport(file).then(r => r.data),
    onSuccess: (d) => {
      setErr(''); setMsg(`تم الاستيراد: ${d.rows ?? 0} صف · جديد ${d.created ?? 0} · تحديث ${d.updated ?? 0}`
        + (d.master_skipped ? ` · تم تخطي ${d.master_skipped} صف من شيتات 2020 الرئيسية (تُستورد بأمر --create-only فقط)` : ''))
      setFile(null); if (fileRef.current) fileRef.current.value = ''
      onDone()
    },
    onError: (e) => { setMsg(''); setErr(errOf(e, 'تعذّر قراءة الملف')) },
  })
  const propose = useMutation({
    mutationFn: () => glApi.partiesPropose().then(r => r.data),
    onSuccess: (d) => {
      setErr('')
      setMsg(`اكتملت المطابقة: مطابقة تامة ${d?.exact ?? 0} · بالكلمات ${d?.tokens ?? 0} · بدون ${d?.none ?? 0}`)
      onDone()
    },
    onError: (e) => { setMsg(''); setErr(errOf(e, 'تعذّر تنفيذ المطابقة')) },
  })
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-gray-700">استيراد أطراف الحسابات (Excel)</span>
        <input ref={fileRef} type="file" accept=".xlsx" className="text-xs"
               onChange={e => { setFile(e.target.files?.[0] || null); setMsg(''); setErr('') }} />
        <button type="button" className={btnPlain} disabled={!file || imp.isPending} onClick={() => imp.mutate()}>
          {imp.isPending ? 'جاري الاستيراد…' : 'استيراد'}
        </button>
        <button type="button" className={btnPrimary} disabled={propose.isPending} onClick={() => propose.mutate()}
                data-tour="finance-gl-parties-propose">
          {propose.isPending ? 'جاري المطابقة…' : 'اقتراح المطابقة'}
        </button>
      </div>
      {msg && <div className="text-sm text-green-700">{msg}</div>}
      <ErrorBox>{err}</ErrorBox>
    </div>
  )
}

// ── confirm many at once from the reviewed suggestions sheet (ledger.approve) ─
const OUTCOMES = {
  will_confirm: { label: 'سيتأكد', cls: 'text-green-700' },
  confirmed:    { label: 'تأكد', cls: 'text-green-700' },
  unchanged:    { label: 'بدون تغيير', cls: 'text-gray-500' },
  error:        { label: 'مرفوض', cls: 'text-red-600' },
}

function ConfirmUploadBar({ onDone }) {
  const fileRef = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [done, setDone] = useState(null)
  const [err, setErr] = useState('')
  const reset = () => { setFile(null); setPreview(null); if (fileRef.current) fileRef.current.value = '' }
  const run = useMutation({
    mutationFn: (dryRun) => glApi.partiesConfirmUpload(file, dryRun).then(r => r.data),
    onSuccess: (d) => {
      setErr('')
      if (d.applied) { setDone(d); reset(); onDone() } else { setDone(null); setPreview(d) }
    },
    onError: (e) => setErr(errOf(e, 'تعذّر قراءة الملف')),
  })
  const shown = preview || done
  const c = shown?.counts || {}
  const toConfirm = c.will_confirm || 0
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 space-y-2" data-tour="finance-gl-parties-confirm-upload">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-gray-700">تأكيد من ملف المراجعة (Excel)</span>
        <input ref={fileRef} type="file" accept=".xlsx" className="text-xs"
               onChange={e => { setFile(e.target.files?.[0] || null); setPreview(null); setDone(null); setErr('') }} />
        <button type="button" className={btnPlain} disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
          {run.isPending && !preview ? 'جاري القراءة…' : 'معاينة'}
        </button>
        {preview && toConfirm > 0 && (
          <button type="button" className={btnPrimary} disabled={run.isPending} onClick={() => run.mutate(false)}>
            {run.isPending ? 'جاري التأكيد…' : `تأكيد ${toConfirm} طرف`}
          </button>
        )}
        {preview && <button type="button" className={btnPlain} onClick={reset}>إلغاء</button>}
      </div>
      <div className="text-xs text-gray-500">
        الملف فيه أعمدة «النوع» و«كود المالية» و«الكود المعتمد». الصفوف اللي «الكود المعتمد» فيها فاضي بتتجاهل.
      </div>
      {shown && (
        <div className="text-sm">
          {done ? 'تم: ' : 'المعاينة: '}
          {Object.entries(OUTCOMES).filter(([k]) => c[k]).map(([k, o]) => (
            <span key={k} className={`me-3 ${o.cls}`}>{o.label} {c[k]}</span>
          ))}
        </div>
      )}
      {shown && shown.results?.some(r => r.outcome === 'error') && (
        <div className="max-h-48 overflow-y-auto border border-red-100 rounded-lg">
          <table className="w-full text-xs">
            <tbody>
              {shown.results.filter(r => r.outcome === 'error').map(r => (
                <tr key={r.row} className="border-t border-red-50">
                  <td className="px-2 py-1 text-gray-500 whitespace-nowrap">سطر {r.row}</td>
                  <td className="px-2 py-1 font-mono">{r.code ?? ''}</td>
                  <td className="px-2 py-1">{r.name ?? ''}</td>
                  <td className="px-2 py-1 font-mono">{r.personcode ?? ''}</td>
                  <td className="px-2 py-1 text-red-600">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorBox>{err}</ErrorBox>
    </div>
  )
}

export default function GLPartiesPage() {
  const qc = useQueryClient()
  const perms = usePermissions('ledger')
  const [status, setStatus] = useState('proposed')
  const [type, setType] = useState('')
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [extra, setExtra] = useState([])           // further cursor pages
  const [next, setNext] = useState(null)
  const [picking, setPicking] = useState(null)
  const [err, setErr] = useState('')

  const listQ = useQuery({
    queryKey: ['gl', 'parties', status, type, dq],
    queryFn: () => glApi.parties({ status: status || undefined, type: type || undefined, q: dq || undefined })
      .then(r => r.data),
    placeholderData: (prev) => prev,
  })
  useEffect(() => { setExtra([]); setNext(listQ.data?.next || null) }, [listQ.data])
  const more = useMutation({
    mutationFn: () => glApi.partiesPage(next).then(r => r.data),
    onSuccess: (d) => { setExtra(x => [...x, ...listOf(d)]); setNext(d.next || null) },
    onError: (e) => setErr(errOf(e)),
  })
  const rows = useMemo(() => [...listOf(listQ.data), ...extra], [listQ.data, extra])
  const { sorted, headerProps } = useSortableRows(rows, {
    persistKey: 'gl-parties', defaultSort: { key: 'code', dir: 'asc', type: 'text' },
  })

  const refresh = () => qc.invalidateQueries({ queryKey: ['gl', 'parties'] })
  const confirm = useMutation({
    mutationFn: ({ id, personcode }) => glApi.partyConfirm(id, personcode),
    onSuccess: () => { setErr(''); setPicking(null); refresh() },
    onError: (e) => setErr(errOf(e, 'تعذّر التأكيد')),
  })
  const reject = useMutation({
    mutationFn: (id) => glApi.partyReject(id),
    onSuccess: () => { setErr(''); refresh() },
    onError: (e) => setErr(errOf(e, 'تعذّر الرفض')),
  })

  const canApprove = !!perms.approve
  const kb = useGridKeyboard({
    rows: sorted, getKey: r => r.id, enabled: canApprove,
    onConfirm: (r) => { if (r.status === 'proposed' && r.softech_personcode && !confirm.isPending) confirm.mutate({ id: r.id, personcode: r.softech_personcode }) },
    onOpen: (r) => setPicking(r.id),
    onClose: () => setPicking(null),
    advanceOnConfirm: true,
  })

  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex flex-wrap items-center gap-2">
        <select className={inputCls} value={status} onChange={e => setStatus(e.target.value)}>
          <option value="">كل الحالات</option>
          {Object.entries(STATUSES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <select className={inputCls} value={type} onChange={e => setType(e.target.value)}>
          <option value="">كل الأنواع</option>
          {Object.entries(PARTY_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <input className={`${inputCls} w-64`} placeholder="بحث بالكود أو الاسم (* أو % للبدل)" value={q}
               onChange={e => setQ(e.target.value)} />
        <span className="text-xs text-gray-500 ms-auto">{rows.length}{next ? '+' : ''} طرف</span>
      </div>

      {perms.edit && <ImportBar onDone={refresh} />}
      {canApprove && <ConfirmUploadBar onDone={refresh} />}
      <ErrorBox>{err || (listQ.isError ? errOf(listQ.error, 'تعذّر تحميل الأطراف') : '')}</ErrorBox>

      <div {...kb.containerProps}
           className={`bg-white rounded-xl border border-gray-200 overflow-x-auto ${kb.containerProps.className}`}
           data-tour="finance-gl-parties-grid">
        {listQ.isLoading ? <SkeletonTable rows={8} cols={7} /> : !sorted.length ? (
          <EmptyState title="لا توجد أطراف" sub={status === 'proposed' ? 'لا اقتراحات بانتظار التأكيد — استورد الأطراف ثم اضغط «اقتراح المطابقة»' : 'غيّر الفلتر'} />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...headerProps('code', 'text')} className="text-right px-3 py-2">الكود</SortTh>
                <SortTh {...headerProps('name')} className="text-right px-3 py-2">الاسم</SortTh>
                <SortTh {...headerProps('party_type')} className="text-right px-3 py-2">النوع</SortTh>
                <SortTh {...headerProps('softech_name')} className="text-right px-3 py-2">الشخص في SOFTECH</SortTh>
                <SortTh {...headerProps('proposal_basis')} className="text-right px-3 py-2">الأساس</SortTh>
                <SortTh {...headerProps('status')} className="text-right px-3 py-2">الحالة</SortTh>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {sorted.map(p => (
                <Fragment key={p.id}>
                  <tr {...kb.rowProps(p)} className={`border-t border-gray-100 hover:bg-gray-50 ${kb.rowProps(p).className}`}>
                    <td className="px-3 py-1.5 font-mono">{p.code}</td>
                    <td className="px-3 py-1.5">{p.name}</td>
                    <td className="px-3 py-1.5">{PARTY_TYPES[p.party_type] || p.party_type}</td>
                    <td className="px-3 py-1.5">
                      {p.softech_personcode
                        ? <><span className="font-mono text-gray-500">{p.softech_personcode}</span> · {p.softech_name || '—'}</>
                        : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-3 py-1.5 text-xs text-gray-600">{BASIS[p.proposal_basis] || '—'}</td>
                    <td className="px-3 py-1.5">
                      <span className={`inline-block px-2 py-0.5 rounded-full border text-xs ${STATUS_CLS[p.status] || ''}`}>
                        {STATUSES[p.status] || p.status}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      {canApprove && (
                        <div className="flex gap-1 justify-end">
                          {p.status === 'proposed' && p.softech_personcode && (
                            <button type="button" className="text-xs text-green-700 hover:underline" disabled={confirm.isPending}
                                    onClick={() => confirm.mutate({ id: p.id, personcode: p.softech_personcode })}>تأكيد</button>
                          )}
                          <button type="button" className="text-xs text-blue-700 hover:underline"
                                  onClick={() => setPicking(picking === p.id ? null : p.id)}>شخص آخر</button>
                          {p.status !== 'rejected' && (
                            <button type="button" className="text-xs text-red-600 hover:underline" disabled={reject.isPending}
                                    onClick={() => reject.mutate(p.id)}>رفض</button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                  {picking === p.id && (
                    <tr><td colSpan={7} className="px-3 py-2">
                      <PersonPicker party={p} busy={confirm.isPending} onClose={() => setPicking(null)}
                                    onPick={(pc) => confirm.mutate({ id: p.id, personcode: pc })} />
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {canApprove && sorted.length > 0 && <div className="text-xs text-gray-400">{GRID_KEYS_HINT}</div>}
      {next && (
        <button type="button" className={btnPlain} disabled={more.isPending} onClick={() => more.mutate()}>
          {more.isPending ? 'جاري التحميل…' : 'عرض المزيد'}
        </button>
      )}
    </div>
  )
}
