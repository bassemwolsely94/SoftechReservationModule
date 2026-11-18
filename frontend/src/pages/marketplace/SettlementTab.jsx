/**
 * «💰 التسويات» — upload a platform payout file (.csv / .xlsx) with its period and a column map
 * (file column name per value); the server imports and matches every line to our orders and returns the
 * counts. Below: earlier payouts and the exception lines of the selected one. Upload needs `edit`.
 */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { marketplaceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useSortableRows from '../../hooks/useSortableRows'
import { btnPrimary, dateTime, errText, inputCls, money, rowsOf, useChannels, useNotice } from './shared'

const MAP_FIELDS = [
  ['external_id', 'رقم الطلب'], ['gross', 'الإجمالي'], ['commission', 'العمولة'], ['delivery_fee', 'رسوم التوصيل'], ['net', 'الصافي'],
]
const MATCH = { matched: 'مطابق', unmatched: 'غير موجود', amount_mismatch: 'اختلاف مبلغ', not_in_file: 'غير موجود بالملف' }
const MATCH_STYLE = { matched: 'text-emerald-700', unmatched: 'text-red-600', amount_mismatch: 'text-amber-700', not_in_file: 'text-red-600' }
const EXCEPTIONS = ['unmatched', 'amount_mismatch', 'not_in_file']
const DEFAULT_MAP = { external_id: 'order_id', gross: 'gross', commission: 'commission', delivery_fee: 'delivery_fee', net: 'net' }

function Counts({ counts }) {
  if (!counts) return null
  return (
    <span className="flex flex-wrap gap-2 text-xs">
      {Object.keys(MATCH).map(k => (
        <span key={k} className={MATCH_STYLE[k]}>{MATCH[k]}: <b>{counts[k] ?? 0}</b></span>
      ))}
    </span>
  )
}

function BatchLines({ id }) {
  const [status, setStatus] = useState('')
  const q = useQuery({
    queryKey: ['marketplace', 'settlement', id, status],
    queryFn: () => marketplaceApi.settlement(id, status ? { status } : {}).then(r => r.data),
  })
  const lines = (q.data?.lines || []).filter(l => status || EXCEPTIONS.includes(l.match_status))
  const table = useSortableRows(lines, { persistKey: 'mp-settlement-lines' })
  return (
    <div className="bg-white rounded-xl border p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-medium text-gray-800">أسطر التسوية {q.data ? `· ${q.data.file_name}` : ''}</h4>
        <select value={status} onChange={e => setStatus(e.target.value)} className={`${inputCls} ms-auto`} aria-label="نتيجة المطابقة">
          <option value="">غير المطابق فقط</option>
          {Object.entries(MATCH).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-gray-500 text-xs">
            <tr>
              <SortTh {...table.headerProps('external_id')} className="text-start px-2 py-1">رقم الطلب</SortTh>
              <SortTh {...table.headerProps('gross', 'number')} className="text-start px-2 py-1">الإجمالي</SortTh>
              <SortTh {...table.headerProps('commission', 'number')} className="text-start px-2 py-1">العمولة</SortTh>
              <SortTh {...table.headerProps('delivery_fee', 'number')} className="text-start px-2 py-1">التوصيل</SortTh>
              <SortTh {...table.headerProps('net', 'number')} className="text-start px-2 py-1">الصافي</SortTh>
              <SortTh {...table.headerProps('match_status')} className="text-start px-2 py-1">النتيجة</SortTh>
              <SortTh {...table.headerProps('note')} className="text-start px-2 py-1">ملاحظة</SortTh>
            </tr>
          </thead>
          <tbody>
            {q.isLoading && <tr><td colSpan={7} className="py-4 text-center text-gray-400">جاري التحميل…</td></tr>}
            {!q.isLoading && lines.length === 0 && <tr><td colSpan={7} className="py-4 text-center text-gray-400">لا توجد أسطر.</td></tr>}
            {table.sorted.map(l => (
              <tr key={l.id} className="border-t">
                <td className="px-2 py-1" dir="ltr">{l.external_id}</td>
                <td className="px-2 py-1">{money(l.gross)}</td>
                <td className="px-2 py-1">{money(l.commission)}</td>
                <td className="px-2 py-1">{money(l.delivery_fee)}</td>
                <td className="px-2 py-1">{money(l.net)}</td>
                <td className={`px-2 py-1 ${MATCH_STYLE[l.match_status] || ''}`}>{MATCH[l.match_status] || l.match_status}</td>
                <td className="px-2 py-1 text-xs text-gray-500">{l.note || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function SettlementTab({ canEdit }) {
  const qc = useQueryClient()
  const [noticeBar, toast] = useNotice()
  const channels = useChannels()
  const fileRef = useRef(null)
  const [f, setF] = useState({ channel: '', period_from: '', period_to: '' })
  const [file, setFile] = useState(null)
  const [cmap, setCmap] = useState(DEFAULT_MAP)
  const [result, setResult] = useState(null)
  const [openId, setOpenId] = useState(null)
  const batches = useQuery({ queryKey: ['marketplace', 'settlements'], queryFn: () => marketplaceApi.settlements().then(r => rowsOf(r.data)) })
  const table = useSortableRows(batches.data || [], {
    persistKey: 'mp-settlements', defaultSort: { key: 'uploaded_at', dir: 'desc', type: 'date' },
    getValue: (r, k) => (EXCEPTIONS.includes(k) ? r.counts?.[k] : k === 'matched' ? r.counts?.matched : r[k]),
  })
  const upload = useMutation({
    mutationFn: () => marketplaceApi.uploadSettlement({ ...f, file, column_map: cmap }).then(r => r.data),
    onSuccess: (d) => {
      setResult(d); setOpenId(d.id); setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      qc.invalidateQueries({ queryKey: ['marketplace', 'settlements'] })
      toast.ok('تم رفع الملف ومطابقته')
    },
    onError: (e) => toast.error(errText(e)),
  })
  const ready = canEdit && f.channel && file && cmap.external_id.trim()

  return (
    <div className="space-y-3">
      {canEdit && (
        <div className="bg-white rounded-xl border p-3 space-y-2" data-tour="marketplace-settlement-upload">
          <div className="grid sm:grid-cols-4 gap-2 text-sm text-gray-600">
            <label className="flex flex-col">المنصة
              <select value={f.channel} onChange={e => setF(x => ({ ...x, channel: e.target.value }))} className={inputCls}>
                <option value="">اختر…</option>
                {(channels.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label className="flex flex-col">من
              <input type="date" value={f.period_from} onChange={e => setF(x => ({ ...x, period_from: e.target.value }))} className={inputCls} />
            </label>
            <label className="flex flex-col">إلى
              <input type="date" value={f.period_to} onChange={e => setF(x => ({ ...x, period_to: e.target.value }))} className={inputCls} />
            </label>
            <label className="flex flex-col">الملف (CSV أو Excel)
              <input ref={fileRef} type="file" accept=".csv,.xlsx" onChange={e => setFile(e.target.files?.[0] || null)} className="text-sm mt-1" />
            </label>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1">اسم العمود في الملف لكل قيمة (رقم الطلب إلزامي؛ الفارغ يُترك)</div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {MAP_FIELDS.map(([k, label]) => (
                <label key={k} className="flex flex-col text-xs text-gray-500">{label}
                  <input value={cmap[k]} onChange={e => setCmap(m => ({ ...m, [k]: e.target.value }))} dir="ltr" className={inputCls} />
                </label>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button disabled={!ready || upload.isPending} onClick={() => upload.mutate()} className={btnPrimary}>
              {upload.isPending ? 'جاري الرفع…' : 'رفع ومطابقة'}
            </button>
            {result && <Counts counts={result.match || result.counts} />}
          </div>
          {noticeBar}
        </div>
      )}

      <div className="bg-white rounded-xl border overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs">
            <tr>
              <SortTh {...table.headerProps('uploaded_at', 'date')} className="text-start px-3 py-2">الرفع</SortTh>
              <SortTh {...table.headerProps('channel_name')} className="text-start px-3 py-2">المنصة</SortTh>
              <SortTh {...table.headerProps('period_from', 'date')} className="text-start px-3 py-2">الفترة</SortTh>
              <SortTh {...table.headerProps('file_name')} className="text-start px-3 py-2">الملف</SortTh>
              <SortTh {...table.headerProps('matched', 'number')} className="text-start px-3 py-2">مطابق</SortTh>
              <SortTh {...table.headerProps('unmatched', 'number')} className="text-start px-3 py-2">غير موجود</SortTh>
              <SortTh {...table.headerProps('amount_mismatch', 'number')} className="text-start px-3 py-2">اختلاف مبلغ</SortTh>
              <SortTh {...table.headerProps('not_in_file', 'number')} className="text-start px-3 py-2">غير موجود بالملف</SortTh>
            </tr>
          </thead>
          <tbody>
            {batches.isLoading && <tr><td colSpan={8} className="py-6 text-center text-gray-400">جاري التحميل…</td></tr>}
            {batches.isError && <tr><td colSpan={8} className="py-6 text-center text-red-600">{errText(batches.error)}</td></tr>}
            {!batches.isLoading && !batches.isError && table.sorted.length === 0 && (
              <tr><td colSpan={8} className="py-6 text-center text-gray-400">لا توجد تسويات مرفوعة.</td></tr>
            )}
            {table.sorted.map(b => (
              <tr key={b.id} onClick={() => setOpenId(b.id)}
                className={`border-t cursor-pointer hover:bg-gray-50 ${openId === b.id ? 'bg-brand-50' : ''}`}>
                <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{dateTime(b.uploaded_at)}<div className="text-xs">{b.uploaded_by_name}</div></td>
                <td className="px-3 py-2">{b.channel_name}</td>
                <td className="px-3 py-2 whitespace-nowrap">{b.period_from || '—'} ← {b.period_to || '—'}</td>
                <td className="px-3 py-2" dir="ltr">{b.file_name}</td>
                <td className="px-3 py-2 text-emerald-700">{b.counts?.matched ?? 0}</td>
                <td className="px-3 py-2 text-red-600">{b.counts?.unmatched ?? 0}</td>
                <td className="px-3 py-2 text-amber-700">{b.counts?.amount_mismatch ?? 0}</td>
                <td className="px-3 py-2 text-red-600">{b.counts?.not_in_file ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {openId && <BatchLines key={openId} id={openId} />}
    </div>
  )
}
