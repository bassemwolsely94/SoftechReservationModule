/**
 * «🏷️ الأصناف المعروضة» — items added to a platform. Nothing is listed until a supervisor approves it
 * (server-side `marketplace.approve`); prescription items are listed only by that explicit decision.
 * `problem`, `qty` (for the chosen branch) and `price` are computed by the server.
 * Keyboard: ↑↓ move · Enter approve / unapprove the active row.
 */
import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { marketplaceApi } from '../../api/client'
import ItemSearchInput from '../../components/ItemSearchInput'
import SortTh from '../../components/SortTh'
import useServerSort from '../../hooks/useServerSort'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useBranchLabels from '../../hooks/useBranchLabels'
import {
  LISTING_PROBLEM, Pager, btnQuiet, dateTime, errText, inputCls, money, qtyText, rowsOf, useChannels, useNotice,
} from './shared'

const ORDERING = ['item', 'code', 'channel', 'approved', 'approved_at']

export default function ListingsTab({ canCreate, canApprove }) {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [noticeBar, toast] = useNotice()
  const channels = useChannels()
  const [channel, setChannel] = useState('')
  const [branch, setBranch] = useState('')
  const [approved, setApproved] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('item')
  const [sku, setSku] = useState('')
  const sort = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: ORDERING, defaultOrdering: 'item' })

  const stores = useQuery({
    queryKey: ['marketplace', 'stores', { channel }],
    queryFn: () => marketplaceApi.stores({ channel }).then(r => rowsOf(r.data)),
    enabled: !!channel,
  })
  const branchOptions = useMemo(() => stores.data || [], [stores.data])
  const params = { page, ordering: ordering || undefined, channel: channel || undefined, branch: branch || undefined,
                   approved: approved || undefined, q: q.trim() || undefined }
  const list = useQuery({
    queryKey: ['marketplace', 'listings', params],
    queryFn: () => marketplaceApi.listings(params).then(r => r.data),
  })
  const rows = rowsOf(list.data)
  const refresh = () => qc.invalidateQueries({ queryKey: ['marketplace', 'listings'] })

  const add = useMutation({
    mutationFn: (item) => marketplaceApi.createListing({ channel: Number(channel), item: item.item_id, external_sku: sku.trim() }).then(r => r.data),
    onSuccess: (d) => { setSku(''); refresh(); toast.ok(`أُضيف ${d.item_name} — غير معتمد حتى يعتمده مشرف.`) },
    onError: (e) => toast.error(errText(e)),
  })
  const toggle = useMutation({
    mutationFn: (row) => (row.approved ? marketplaceApi.unapprove(row.id) : marketplaceApi.approve(row.id)).then(r => r.data),
    onSuccess: (d) => { refresh(); toast.ok(d.approved ? `اعتُمد ${d.item_name}` : `أُلغي اعتماد ${d.item_name}`) },
    onError: (e) => toast.error(errText(e)),
  })
  const pick = (item) => {
    if (!channel) { toast.error('اختر المنصة أولًا.'); return }
    if (!item?.item_id) { toast.error('الصنف غير موجود في كتالوج النظام.'); return }
    add.mutate(item)
  }
  const getKey = useCallback(r => r.id, [])
  const kb = useGridKeyboard({
    rows, getKey, enabled: true,
    onConfirm: canApprove ? (r => { if (!toggle.isPending) toggle.mutate(r) }) : undefined,
  })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-end">
        <label className="flex flex-col text-xs text-gray-500">المنصة
          <select value={channel} onChange={e => { setChannel(e.target.value); setBranch(''); setPage(1) }} className={inputCls}>
            <option value="">كل المنصات</option>
            {(channels.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-500">الكمية في فرع
          <select value={branch} onChange={e => { setBranch(e.target.value); setPage(1) }} className={inputCls} disabled={!channel}>
            <option value="">فرعي</option>
            {branchOptions.map(s => <option key={s.id} value={s.branch}>{bl(s.branch_code) || s.branch_name}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-500">الاعتماد
          <select value={approved} onChange={e => { setApproved(e.target.value); setPage(1) }} className={inputCls}>
            <option value="">الكل</option>
            <option value="1">معتمد</option>
            <option value="0">غير معتمد</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-500">بحث في القائمة
          <input value={q} onChange={e => { setQ(e.target.value); setPage(1) }} placeholder="اسم أو كود" className={inputCls} />
        </label>
      </div>

      {canCreate && (
        <div className="bg-white rounded-xl border p-3 flex flex-wrap items-end gap-2">
          <div className="flex-1 min-w-[16rem]">
            <div className="text-xs text-gray-500 mb-1">إضافة صنف للمنصة {channel ? '' : '(اختر المنصة أولًا)'}</div>
            <ItemSearchInput onSelect={pick} disabled={!channel || add.isPending} placeholder="ابحث عن الصنف ثم Enter لإضافته" />
          </div>
          <label className="flex flex-col text-xs text-gray-500">كود الصنف عند المنصة (اختياري)
            <input value={sku} onChange={e => setSku(e.target.value)} className={`${inputCls} w-40`} dir="ltr" />
          </label>
        </div>
      )}
      {noticeBar}

      <div className="bg-white rounded-xl border overflow-x-auto" {...kb.containerProps} data-tour="marketplace-listings-grid">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs">
            <tr>
              <SortTh {...sort.headerProps('item')} className="text-start px-3 py-2">الصنف</SortTh>
              <SortTh {...sort.headerProps('code')} className="text-start px-3 py-2">الكود</SortTh>
              <SortTh {...sort.headerProps('channel')} className="text-start px-3 py-2">المنصة</SortTh>
              <th className="text-start px-3 py-2">المشكلة</th>
              <th className="text-start px-3 py-2">الكمية المتاحة</th>
              <th className="text-start px-3 py-2">سعر المنصة</th>
              <SortTh {...sort.headerProps('approved')} className="text-start px-3 py-2">الاعتماد</SortTh>
              <SortTh {...sort.headerProps('approved_at', 'date')} className="text-start px-3 py-2">اعتُمد في</SortTh>
            </tr>
          </thead>
          <tbody>
            {list.isLoading && <tr><td colSpan={8} className="py-10 text-center text-gray-400">جاري التحميل…</td></tr>}
            {list.isError && <tr><td colSpan={8} className="py-10 text-center text-red-600">{errText(list.error)}</td></tr>}
            {!list.isLoading && !list.isError && rows.length === 0 && (
              <tr><td colSpan={8} className="py-10 text-center text-gray-400">لا توجد أصناف مضافة. لا يُعرض شيء على أي منصة بدون إضافة واعتماد.</td></tr>
            )}
            {rows.map(r => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.id} {...rp} className={`border-t ${rp.className}`}>
                  <td className="px-3 py-2" dir="ltr">{r.item_name}{r.external_sku && <span className="text-xs text-gray-400"> · {r.external_sku}</span>}</td>
                  <td className="px-3 py-2 text-gray-500">{r.item_code}</td>
                  <td className="px-3 py-2">{r.channel_name}</td>
                  <td className={`px-3 py-2 ${r.problem ? 'text-red-600' : 'text-emerald-700'}`}>{LISTING_PROBLEM[r.problem] ?? r.problem}</td>
                  <td className="px-3 py-2">{qtyText(r.qty)}</td>
                  <td className="px-3 py-2">{money(r.price)}</td>
                  <td className="px-3 py-2">
                    {canApprove ? (
                      <button disabled={toggle.isPending} onClick={() => toggle.mutate(r)}
                        className={r.approved ? `${btnQuiet} text-emerald-700` : btnQuiet}>
                        {r.approved ? '✓ معتمد — إلغاء' : 'اعتماد'}
                      </button>
                    ) : (r.approved ? <span className="text-emerald-700">✓ معتمد</span> : <span className="text-gray-400">غير معتمد</span>)}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-500">{r.approved_at ? `${dateTime(r.approved_at)} · ${r.approved_by_name}` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <Pager page={page} setPage={setPage} data={list.data} />
        <div className="px-3 py-1 text-[11px] text-gray-400">⌨ ↑↓ تنقل{canApprove ? ' · Enter اعتماد / إلغاء الاعتماد' : ''}</div>
      </div>
    </div>
  )
}
