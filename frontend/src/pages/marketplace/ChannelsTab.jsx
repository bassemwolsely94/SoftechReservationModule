/**
 * «🔌 المنصات والفروع» — platform setup (SOFTECH account code, price rule, buffer), the platform's branch
 * stores, the stock push and its log. Writes need marketplace `edit` (enforced server-side).
 * While MARKETPLACE_PUSH_ENABLED is off the server only logs the payload (PushLog.dry_run = true) and
 * this tab says «تجريبي — لا يُرسل». Credentials are write-only and never shown.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi, marketplaceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useSortableRows from '../../hooks/useSortableRows'
import useServerSort from '../../hooks/useServerSort'
import useBranchLabels from '../../hooks/useBranchLabels'
import { Pager, btnPrimary, btnQuiet, dateTime, errText, inputCls, rowsOf, useChannels, useNotice } from './shared'

const ADAPTERS = { manual: 'يدوي', fake: 'تجريبي' }
const SCOPES = { per_branch: 'لكل فرع', national: 'على مستوى الشركة' }
const PRICE_RULES = { shelf: 'سعر الرف', shelf_plus_pct: 'سعر الرف + نسبة' }
const MODES = { platform_rider: 'مندوب المنصة', own_rider: 'مندوبنا' }
const EDIT_FIELDS = ['name', 'adapter', 'scope', 'softech_personcode', 'price_rule', 'price_pct', 'stock_buffer', 'max_qty_per_item', 'is_active']
const DRY_RUN = 'تجريبي — لا يُرسل'

function ChannelEditor({ channel, canEdit, toast }) {
  const qc = useQueryClient()
  const [f, setF] = useState(null)
  useEffect(() => { setF(Object.fromEntries(EDIT_FIELDS.map(k => [k, channel[k] ?? '']))) }, [channel])
  const save = useMutation({
    mutationFn: () => marketplaceApi.updateChannel(channel.id, {
      ...f, max_qty_per_item: f.max_qty_per_item === '' ? null : f.max_qty_per_item,
    }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['marketplace', 'channels'] }); toast.ok('تم حفظ إعداد المنصة') },
    onError: (e) => toast.error(errText(e)),
  })
  if (!f) return null
  const set = (k) => (e) => setF(x => ({ ...x, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const sel = (k, opts) => (
    <select value={f[k]} onChange={set(k)} disabled={!canEdit} className={inputCls}>
      {Object.entries(opts).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
  return (
    <div className="bg-white rounded-xl border p-3 space-y-2" data-tour="marketplace-channel-settings">
      <div className="flex items-center gap-2">
        <h3 className="font-bold text-gray-900">{channel.name}</h3>
        <span className="text-xs text-gray-400" dir="ltr">{channel.code}</span>
        {channel.has_credentials && <span className="text-xs text-gray-500">· بيانات الاعتماد مسجلة</span>}
      </div>
      <div className="grid sm:grid-cols-3 gap-2 text-sm text-gray-600">
        <label className="flex flex-col">الاسم<input value={f.name} onChange={set('name')} disabled={!canEdit} className={inputCls} /></label>
        <label className="flex flex-col">المحوّل{sel('adapter', ADAPTERS)}</label>
        <label className="flex flex-col">النطاق{sel('scope', SCOPES)}</label>
        <label className="flex flex-col">كود حساب المنصة في SOFTECH
          <input value={f.softech_personcode} onChange={set('softech_personcode')} disabled={!canEdit} className={inputCls} dir="ltr" />
        </label>
        <label className="flex flex-col">قاعدة السعر{sel('price_rule', PRICE_RULES)}</label>
        <label className="flex flex-col">نسبة السعر %
          <input value={f.price_pct} onChange={set('price_pct')} disabled={!canEdit || f.price_rule !== 'shelf_plus_pct'} className={inputCls} inputMode="decimal" />
        </label>
        <label className="flex flex-col">احتياطي المخزون
          <input value={f.stock_buffer} onChange={set('stock_buffer')} disabled={!canEdit} className={inputCls} inputMode="decimal" />
        </label>
        <label className="flex flex-col">أقصى كمية للصنف (فارغ = بلا حد)
          <input value={f.max_qty_per_item ?? ''} onChange={set('max_qty_per_item')} disabled={!canEdit} className={inputCls} inputMode="numeric" />
        </label>
        <label className="flex items-center gap-2 mt-5">
          <input type="checkbox" checked={!!f.is_active} onChange={set('is_active')} disabled={!canEdit} /> مفعّلة
        </label>
      </div>
      <p className="text-[11px] text-gray-400">كل طلبات المنصة تُسجَّل بيعًا آجلًا على هذا الحساب كمسودة في نقطة البيع؛ الكاشير يكمّلها. سعر المسودة = تسعير نقطة البيع العادي.</p>
      {canEdit && <button onClick={() => save.mutate()} disabled={save.isPending} className={btnPrimary}>حفظ</button>}
    </div>
  )
}

function Stores({ channel, canEdit, toast }) {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const branches = useQuery({ queryKey: ['marketplace', 'branch-options'], queryFn: () => branchesApi.list().then(r => rowsOf(r.data)), enabled: canEdit })
  const stores = useQuery({
    queryKey: ['marketplace', 'stores', { channel: String(channel.id) }],
    queryFn: () => marketplaceApi.stores({ channel: channel.id }).then(r => rowsOf(r.data)),
  })
  const [nb, setNb] = useState({ branch: '', external_store_id: '', delivery_mode: 'platform_rider' })
  const refresh = () => qc.invalidateQueries({ queryKey: ['marketplace', 'stores'] })
  const create = useMutation({
    mutationFn: () => marketplaceApi.createStore({ ...nb, channel: channel.id, branch: Number(nb.branch), is_active: false }).then(r => r.data),
    onSuccess: () => { setNb({ branch: '', external_store_id: '', delivery_mode: 'platform_rider' }); refresh(); toast.ok('أُضيف الفرع للمنصة (غير مفعّل)') },
    onError: (e) => toast.error(errText(e)),
  })
  const patch = useMutation({
    mutationFn: ({ id, data }) => marketplaceApi.updateStore(id, data).then(r => r.data),
    onSuccess: () => { refresh(); toast.ok('تم الحفظ') },
    onError: (e) => toast.error(errText(e)),
  })
  const table = useSortableRows(stores.data || [], { persistKey: 'mp-stores', getValue: (r, k) => (k === 'branch' ? bl(r.branch_code) : r[k]) })
  const used = new Set((stores.data || []).map(s => s.branch))
  return (
    <div className="bg-white rounded-xl border p-3 space-y-2">
      <h4 className="font-medium text-gray-800">فروع المنصة</h4>
      <table className="w-full text-sm">
        <thead className="text-gray-500 text-xs">
          <tr>
            <SortTh {...table.headerProps('branch')} className="text-start px-2 py-1">الفرع</SortTh>
            <SortTh {...table.headerProps('external_store_id')} className="text-start px-2 py-1">كود المتجر عند المنصة</SortTh>
            <SortTh {...table.headerProps('delivery_mode')} className="text-start px-2 py-1">التوصيل</SortTh>
            <SortTh {...table.headerProps('is_active')} className="text-start px-2 py-1">مفعّل</SortTh>
          </tr>
        </thead>
        <tbody>
          {stores.isLoading && <tr><td colSpan={4} className="py-4 text-center text-gray-400">جاري التحميل…</td></tr>}
          {!stores.isLoading && table.sorted.length === 0 && <tr><td colSpan={4} className="py-4 text-center text-gray-400">لا توجد فروع لهذه المنصة.</td></tr>}
          {table.sorted.map(s => (
            <tr key={s.id} className="border-t">
              <td className="px-2 py-1">{bl(s.branch_code) || s.branch_name}</td>
              <td className="px-2 py-1">
                <input defaultValue={s.external_store_id} disabled={!canEdit} dir="ltr" className={`${inputCls} w-40`}
                  onBlur={e => { if (e.target.value !== s.external_store_id) patch.mutate({ id: s.id, data: { external_store_id: e.target.value } }) }} />
              </td>
              <td className="px-2 py-1">
                <select value={s.delivery_mode} disabled={!canEdit} className={inputCls}
                  onChange={e => patch.mutate({ id: s.id, data: { delivery_mode: e.target.value } })}>
                  {Object.entries(MODES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </td>
              <td className="px-2 py-1">
                <input type="checkbox" checked={s.is_active} disabled={!canEdit || patch.isPending}
                  onChange={e => patch.mutate({ id: s.id, data: { is_active: e.target.checked } })} aria-label="مفعّل" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {canEdit && (
        <div className="flex flex-wrap items-end gap-2 border-t pt-2">
          <label className="flex flex-col text-xs text-gray-500">فرع جديد
            <select value={nb.branch} onChange={e => setNb(x => ({ ...x, branch: e.target.value }))} className={inputCls}>
              <option value="">اختر…</option>
              {(branches.data || []).filter(b => !used.has(b.id)).map(b => (
                <option key={b.id} value={b.id}>{bl(b.softech_branch_id) || b.name_ar || b.name}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col text-xs text-gray-500">كود المتجر عند المنصة
            <input value={nb.external_store_id} onChange={e => setNb(x => ({ ...x, external_store_id: e.target.value }))} className={`${inputCls} w-40`} dir="ltr" />
          </label>
          <label className="flex flex-col text-xs text-gray-500">التوصيل
            <select value={nb.delivery_mode} onChange={e => setNb(x => ({ ...x, delivery_mode: e.target.value }))} className={inputCls}>
              {Object.entries(MODES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <button disabled={!nb.branch || create.isPending} onClick={() => create.mutate()} className={btnQuiet}>إضافة الفرع</button>
        </div>
      )}
    </div>
  )
}

function PushLog({ channel }) {
  const [page, setPage] = useState(1)
  const [ordering, setOrdering] = useState('-at')
  const bl = useBranchLabels()
  const sort = useServerSort(ordering, o => { setOrdering(o); setPage(1) }, { allowed: ['at', 'kind', 'ok'], defaultOrdering: '-at' })
  const params = { channel: channel.id, page, ordering: ordering || undefined }
  const q = useQuery({ queryKey: ['marketplace', 'push-log', params], queryFn: () => marketplaceApi.pushLog(params).then(r => r.data) })
  const stores = useQuery({
    queryKey: ['marketplace', 'stores', { channel: String(channel.id) }],
    queryFn: () => marketplaceApi.stores({ channel: channel.id }).then(r => rowsOf(r.data)),
  })
  const codeOf = Object.fromEntries((stores.data || []).map(s => [s.branch, s.branch_code]))
  const rows = rowsOf(q.data)
  return (
    <div className="bg-white rounded-xl border p-3">
      <h4 className="font-medium text-gray-800 mb-2">سجل الإرسال</h4>
      <table className="w-full text-sm">
        <thead className="text-gray-500 text-xs">
          <tr>
            <SortTh {...sort.headerProps('at', 'date')} className="text-start px-2 py-1">الوقت</SortTh>
            <SortTh {...sort.headerProps('kind')} className="text-start px-2 py-1">النوع</SortTh>
            <th className="text-start px-2 py-1">الفرع</th>
            <th className="text-start px-2 py-1">الأسطر</th>
            <SortTh {...sort.headerProps('ok')} className="text-start px-2 py-1">النتيجة</SortTh>
          </tr>
        </thead>
        <tbody>
          {!q.isLoading && rows.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-gray-400">لا يوجد إرسال بعد.</td></tr>}
          {rows.map(r => (
            <tr key={r.id} className="border-t">
              <td className="px-2 py-1 text-gray-500 whitespace-nowrap">{dateTime(r.at)}</td>
              <td className="px-2 py-1">{r.kind_label}</td>
              <td className="px-2 py-1">{r.branch ? (bl(codeOf[r.branch]) || '—') : 'كل الفروع'}</td>
              <td className="px-2 py-1">{Array.isArray(r.payload) ? r.payload.length : '—'}</td>
              <td className="px-2 py-1">
                {r.dry_run ? <span className="text-amber-700">{DRY_RUN}</span>
                  : r.ok ? <span className="text-emerald-700">✓ أُرسل</span> : <span className="text-red-600">تعذر الإرسال</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager page={page} setPage={setPage} data={q.data} />
    </div>
  )
}

export default function ChannelsTab({ canEdit }) {
  const qc = useQueryClient()
  const [noticeBar, toast] = useNotice()
  const channels = useChannels()
  const [selected, setSelected] = useState(null)
  const [nc, setNc] = useState({ code: '', name: '' })
  const [lastPush, setLastPush] = useState(null)   // {dry: bool, n: int} from the last push response
  const list = useMemo(() => channels.data || [], [channels.data])
  const current = list.find(c => c.id === selected) || null
  const table = useSortableRows(list, { persistKey: 'mp-channels' })
  useEffect(() => { if (!selected && list.length) setSelected(list[0].id) }, [list, selected])
  useEffect(() => { setLastPush(null) }, [selected])

  const create = useMutation({
    mutationFn: () => marketplaceApi.createChannel({ ...nc, adapter: 'manual', is_active: false }).then(r => r.data),
    onSuccess: (d) => { setNc({ code: '', name: '' }); qc.invalidateQueries({ queryKey: ['marketplace', 'channels'] }); setSelected(d.id); toast.ok('أُضيفت المنصة (غير مفعّلة)') },
    onError: (e) => toast.error(errText(e)),
  })
  const push = useMutation({
    mutationFn: () => marketplaceApi.pushStock(current.id).then(r => r.data),
    onSuccess: (logs) => {
      const rows = Array.isArray(logs) ? logs : []
      const dry = rows.some(l => l.dry_run)
      setLastPush({ dry, n: rows.length })
      qc.invalidateQueries({ queryKey: ['marketplace', 'push-log'] })
      if (!rows.length) { toast.error('لا يوجد فرع مفعّل لهذه المنصة — لم يُرسل شيء.'); return }
      toast.ok(dry ? `${DRY_RUN} — سُجّل ${rows.length} إرسال تجريبي فقط.` : `أُرسل المخزون (${rows.length}).`)
    },
    onError: (e) => toast.error(errText(e)),
  })

  return (
    <div className="grid lg:grid-cols-[16rem_1fr] gap-3">
      <div className="space-y-2">
        <div className="bg-white rounded-xl border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...table.headerProps('name')} className="text-start px-3 py-2">المنصة</SortTh>
                <SortTh {...table.headerProps('is_active')} className="text-start px-3 py-2">الحالة</SortTh>
              </tr>
            </thead>
            <tbody>
              {channels.isLoading && <tr><td colSpan={2} className="py-4 text-center text-gray-400">جاري التحميل…</td></tr>}
              {!channels.isLoading && list.length === 0 && <tr><td colSpan={2} className="py-4 text-center text-gray-400">لا توجد منصات بعد.</td></tr>}
              {table.sorted.map(c => (
                <tr key={c.id} onClick={() => setSelected(c.id)}
                  className={`border-t cursor-pointer hover:bg-gray-50 ${c.id === selected ? 'bg-brand-50 font-medium' : ''}`}>
                  <td className="px-3 py-2">{c.name}</td>
                  <td className="px-3 py-2 text-xs">{c.is_active ? <span className="text-emerald-700">مفعّلة</span> : <span className="text-gray-400">موقوفة</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {canEdit && (
          <div className="bg-white rounded-xl border p-3 space-y-2">
            <div className="text-xs text-gray-500">منصة جديدة</div>
            <input value={nc.code} onChange={e => setNc(x => ({ ...x, code: e.target.value }))} placeholder="الكود (حروف إنجليزية)" dir="ltr" className={`${inputCls} w-full`} />
            <input value={nc.name} onChange={e => setNc(x => ({ ...x, name: e.target.value }))} placeholder="الاسم" className={`${inputCls} w-full`} />
            <button disabled={!nc.code.trim() || !nc.name.trim() || create.isPending} onClick={() => create.mutate()} className={`${btnQuiet} w-full`}>إضافة</button>
          </div>
        )}
      </div>
      <div className="space-y-3">
        {noticeBar}
        {current ? <>
          <ChannelEditor channel={current} canEdit={canEdit} toast={toast} />
          <Stores channel={current} canEdit={canEdit} toast={toast} />
          {canEdit && (
            <div className="flex items-center gap-3">
              <button onClick={() => push.mutate()} disabled={push.isPending} className={btnQuiet} data-tour="marketplace-push-stock">
                ⇪ إرسال المخزون للمنصة
              </button>
              {lastPush?.dry && <span className="text-sm text-amber-700 font-medium">{DRY_RUN}</span>}
              {lastPush?.n > 0 && !lastPush.dry && <span className="text-sm text-emerald-700">أُرسل</span>}
            </div>
          )}
          <PushLog channel={current} />
        </> : !channels.isLoading && <div className="py-10 text-center text-gray-400">اختر منصة أو أضف واحدة.</div>}
      </div>
    </div>
  )
}
