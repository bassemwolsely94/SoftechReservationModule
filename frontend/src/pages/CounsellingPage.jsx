/**
 * CounsellingPage — /counselling «إرشادات الاستخدام» (Project 4, doc 34).
 *
 * Pharmacists write (or start from an AI draft) one usage sheet, tick the items that share it
 * (pack sizes / codes — suggested by name, never linked automatically) and approve it. Only the
 * approved version reaches customers (WhatsApp card, printed label). The server enforces who may
 * edit / approve; buttons here are comfort only.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { counsellingApi } from '../api/client'
import ItemSearchWidget from '../components/ItemSearchWidget'
import SortTh from '../components/SortTh'
import { GUIDANCE_FIELDS } from '../counselling/GuidanceBlock'
import useCounsellingStatus from '../counselling/useCounsellingStatus'
import useHelpTab from '../help/useHelpTab'
import useGridKeyboard from '../hooks/useGridKeyboard'
import { usePermissions } from '../hooks/usePermission'
import useSortableRows from '../hooks/useSortableRows'

const TABS = [
  { key: 'needs', label: 'يحتاج محتوى' },
  { key: 'draft', label: 'مسودات' },
  { key: 'pending_review', label: 'بانتظار الاعتماد' },
  { key: 'approved', label: 'معتمد' },
  { key: 'retired', label: 'مسحوب' },
]
const FOOD = [['', '—'], ['before', 'قبل الأكل'], ['after', 'بعد الأكل'], ['any', 'مع الأكل أو بدونه']]
const FREQ = ['', '1x1', '1x2', '1x3', 'prn']
const errText = e => { const d = e?.response?.data; return d ? (d.detail || Object.values(d).flat().join(' · ')) : (e ? 'حدث خطأ' : '') }
const getKey = r => r.id ?? `i${r.item_id}`

export default function CounsellingPage() {
  const status = useCounsellingStatus()
  const perms = usePermissions('counselling')
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState(params.get('open') ? 'draft' : 'needs')
  const [openId, setOpenId] = useState(params.get('open') ? Number(params.get('open')) : null)
  const [newItem, setNewItem] = useState(params.get('item') ? { id: Number(params.get('item')) } : null)
  useHelpTab(tab)

  const list = useQuery({
    queryKey: ['counselling', tab],
    queryFn: () => (tab === 'needs' ? counsellingApi.needs() : counsellingApi.list({ status: tab }))
      .then(r => r.data.results || []),
    enabled: status.content,
  })
  const rows = list.data || []
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: `counselling-${tab}` })
  const kb = useGridKeyboard({
    rows: sorted, getKey,
    onConfirm: r => (r.id ? setOpenId(r.id) : setNewItem({ id: r.item_id, name: r.name })),
  })

  useEffect(() => { if (openId || newItem) setParams({}, { replace: true }) }, [openId, newItem, setParams])

  if (!status.content) {
    return <div dir="rtl" className="p-6 text-gray-500">شاشة الإرشادات غير مفعّلة بعد.</div>
  }

  return (
    <div dir="rtl" className="p-4 flex gap-4 items-start">
      <div className="flex-1 min-w-0 space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-lg font-bold text-gray-900 flex-1">📘 إرشادات الاستخدام</h1>
          {perms.edit && (
            <div className="w-72" data-tour="counselling-new">
              <ItemSearchWidget onSelect={it => setNewItem(it)} placeholder="إرشاد جديد لصنف…" />
            </div>
          )}
        </div>
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit" data-tour="counselling-tabs">
          {TABS.map(t => (
            <button key={t.key} type="button" onClick={() => setTab(t.key)}
                    className={`text-xs px-3 py-1.5 rounded-lg ${tab === t.key ? 'bg-white shadow font-semibold' : 'text-gray-600'}`}>
              {t.label}
            </button>
          ))}
        </div>

        <div {...kb.containerProps} className="bg-white rounded-xl border overflow-auto" data-tour="counselling-grid">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs">
              {tab === 'needs' ? (
                <tr>
                  <SortTh {...headerProps('name', 'text')}>الصنف</SortTh>
                  <SortTh {...headerProps('softech_id', 'text')}>الكود</SortTh>
                  <SortTh {...headerProps('sold', 'number')}>المباع (30 يوم)</SortTh>
                </tr>
              ) : (
                <tr>
                  <SortTh {...headerProps('title', 'text')}>الإرشاد</SortTh>
                  <th className="p-2 text-right">الأصناف</th>
                  <SortTh {...headerProps('source_label', 'text')}>المصدر</SortTh>
                  <SortTh {...headerProps('version', 'number')}>الإصدار</SortTh>
                  <SortTh {...headerProps('updated_at', 'date')}>آخر تعديل</SortTh>
                </tr>
              )}
            </thead>
            <tbody>
              {sorted.map(r => (
                <tr key={getKey(r)} {...kb.rowProps(r)}
                    onClick={() => (r.id ? setOpenId(r.id) : setNewItem({ id: r.item_id, name: r.name }))}
                    className={`border-t cursor-pointer hover:bg-gray-50 ${kb.rowProps(r).className}`}>
                  {tab === 'needs' ? (
                    <>
                      <td className="p-2">{r.name}</td>
                      <td className="p-2 font-mono text-xs text-gray-500">{r.softech_id}</td>
                      <td className="p-2 tabular-nums">{r.sold}</td>
                    </>
                  ) : (
                    <>
                      <td className="p-2 font-medium">{r.title}{r.has_unapproved_changes && <span className="text-[11px] text-amber-700 mr-1">· تعديل غير معتمد</span>}</td>
                      <td className="p-2 text-xs text-gray-500">{r.items.length}</td>
                      <td className="p-2 text-xs">{r.source_label}</td>
                      <td className="p-2 tabular-nums">{r.version || '—'}</td>
                      <td className="p-2 text-xs text-gray-500">{(r.updated_at || '').slice(0, 10)}</td>
                    </>
                  )}
                </tr>
              ))}
              {!sorted.length && (
                <tr><td colSpan={5} className="p-6 text-center text-gray-400">{list.isLoading ? 'جارٍ التحميل…' : 'لا يوجد'}</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {(openId || newItem) && (
        <Editor key={openId || `new-${newItem.id}`} id={openId} newItem={newItem} perms={perms}
                onOpen={id => { setNewItem(null); setOpenId(id) }}
                onClose={() => { setOpenId(null); setNewItem(null) }} />
      )}
    </div>
  )
}

function Editor({ id, newItem, perms, onOpen, onClose }) {
  const qc = useQueryClient()
  const sheet = useQuery({
    queryKey: ['counselling-sheet', id],
    queryFn: () => counsellingApi.get(id).then(r => r.data),
    enabled: !!id,
  })
  const s = sheet.data
  const [form, setForm] = useState({})
  useEffect(() => { if (s) setForm(Object.fromEntries([...GUIDANCE_FIELDS.map(([k]) => [k, s[k] || '']), ['title', s.title], ['frequency_code', s.frequency_code], ['with_food', s.with_food]])) }, [s])
  const suggestions = useQuery({
    queryKey: ['counselling-suggest', id],
    queryFn: () => counsellingApi.suggest(id).then(r => r.data.results),
    enabled: !!id && perms.edit && s?.status !== 'retired',
  })
  const refresh = data => {
    qc.invalidateQueries({ queryKey: ['counselling'] })
    if (data?.id) qc.setQueryData(['counselling-sheet', data.id], data)
    qc.invalidateQueries({ queryKey: ['counselling-suggest', id] })
  }
  const act = useMutation({ mutationFn: fn => fn().then(r => r.data), onSuccess: refresh })
  const [retireReason, setRetireReason] = useState('')

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const editable = perms.edit && (!s || s.status !== 'retired')
  const dirty = useMemo(() => s && Object.keys(form).some(k => (form[k] ?? '') !== (s[k] ?? '')), [form, s])

  const create = () => act.mutate(() => counsellingApi.create({ ...form, item_ids: [newItem.id] }), {
    onSuccess: d => onOpen(d.id),
  })
  const aiDraft = () => act.mutate(() => counsellingApi.aiDraft(newItem.id), { onSuccess: d => onOpen(d.id) })

  return (
    <aside className="w-[30rem] shrink-0 bg-white rounded-xl border shadow-sm sticky top-4 max-h-[calc(100vh-6rem)] flex flex-col" data-tour="counselling-editor">
      <div className="p-3 border-b flex items-center gap-2">
        <div className="font-semibold text-sm flex-1">{s ? s.title : `إرشاد جديد — ${newItem?.name || ''}`}</div>
        {s && <span className="text-xs rounded-full bg-gray-100 px-2 py-0.5">{s.status_label}{s.version ? ` · إصدار ${s.version}` : ''}</span>}
        <button type="button" onClick={onClose} className="text-gray-500 hover:text-gray-800 px-1">✕</button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3 text-sm">
        {s?.source === 'ai_draft' && s.status !== 'approved' && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 text-amber-900 p-2 text-xs font-semibold">
            مسودة آلية — يجب مراجعة صيدلي قبل الاعتماد{s.ai_model ? ` (${s.ai_model})` : ''}
          </div>
        )}
        {s?.has_unapproved_changes && (
          <div className="rounded-lg bg-sky-50 border border-sky-200 text-sky-900 p-2 text-xs">
            يوجد تعديل غير معتمد — العملاء يرون الإصدار {s.version} حتى تعتمد التعديل.
          </div>
        )}
        {!s && !newItem && <div className="text-gray-400">جارٍ التحميل…</div>}
        {(s || newItem) && (
          <>
            <Field label="العنوان" value={form.title} onChange={v => set('title', v)} disabled={!editable} />
            {GUIDANCE_FIELDS.map(([k, label]) => (
              <Field key={k} label={label} value={form[k]} onChange={v => set(k, v)} disabled={!editable} area />
            ))}
            <div className="flex gap-2">
              <label className="flex-1 text-xs text-gray-500">مع الأكل
                <select value={form.with_food || ''} disabled={!editable} onChange={e => set('with_food', e.target.value)}
                        className="mt-0.5 w-full rounded-lg border px-2 py-1.5 text-sm text-gray-900">
                  {FOOD.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label className="flex-1 text-xs text-gray-500">رمز التكرار (للملصق)
                <select value={form.frequency_code || ''} disabled={!editable} onChange={e => set('frequency_code', e.target.value)}
                        className="mt-0.5 w-full rounded-lg border px-2 py-1.5 text-sm text-gray-900">
                  {FREQ.map(v => <option key={v} value={v}>{v || '—'}</option>)}
                </select>
              </label>
            </div>
          </>
        )}

        {s && (
          <div data-tour="counselling-items">
            <div className="text-xs font-semibold text-gray-500 mb-1">الأصناف المرتبطة ({s.items.length})</div>
            <div className="space-y-1">
              {s.items.map(it => (
                <div key={it.item_id} className="flex items-center gap-2 text-xs border rounded px-2 py-1">
                  <span className="flex-1">{it.name}</span>
                  {editable && s.items.length > 1 && (
                    <button type="button" className="text-red-600" onClick={() => act.mutate(() => counsellingApi.unlink(s.id, it.item_id))}>فك الربط</button>
                  )}
                </div>
              ))}
            </div>
            {editable && suggestions.data?.length > 0 && (
              <div className="mt-2">
                <div className="text-[11px] text-gray-500 mb-1">أصناف مشابهة بالاسم — اربط ما يطابق نفس الدواء فقط</div>
                {suggestions.data.map(it => (
                  <div key={it.item_id} className="flex items-center gap-2 text-xs px-2 py-1">
                    <span className="flex-1 text-gray-700">{it.name}</span>
                    <button type="button" className="text-brand-700" onClick={() => act.mutate(() => counsellingApi.link(s.id, [it.item_id]))}>ربط</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {(act.error || null) && <div className="text-red-700 text-sm">{errText(act.error)}</div>}
      </div>

      <div className="p-3 border-t flex flex-wrap gap-2">
        {!s && newItem && perms.edit && (
          <>
            <button type="button" onClick={create} disabled={act.isPending} className="rounded-lg bg-brand-600 text-white px-3 py-1.5" data-tour="counselling-save">حفظ كمسودة</button>
            <button type="button" onClick={aiDraft} disabled={act.isPending} className="rounded-lg border px-3 py-1.5" data-tour="counselling-ai-draft">مسودة آلية</button>
          </>
        )}
        {s && editable && (
          <>
            <button type="button" disabled={!dirty || act.isPending} onClick={() => act.mutate(() => counsellingApi.update(s.id, form))}
                    className="rounded-lg border px-3 py-1.5 disabled:opacity-40" data-tour="counselling-save">حفظ</button>
            {s.status === 'draft' && !dirty && (
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => counsellingApi.submit(s.id))}
                      className="rounded-lg border px-3 py-1.5" data-tour="counselling-submit">إرسال للاعتماد</button>
            )}
            {perms.approve && ['draft', 'pending_review'].includes(s.status) && !dirty && (
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => counsellingApi.approve(s.id))}
                      className="rounded-lg bg-emerald-600 text-white px-3 py-1.5" data-tour="counselling-approve">اعتماد</button>
            )}
          </>
        )}
        {s && perms.approve && s.status !== 'retired' && (
          <div className="flex gap-1 items-center w-full">
            <input value={retireReason} onChange={e => setRetireReason(e.target.value)} placeholder="سبب السحب"
                   className="flex-1 rounded-lg border px-2 py-1 text-xs" />
            <button type="button" disabled={!retireReason.trim() || act.isPending}
                    onClick={() => act.mutate(() => counsellingApi.retire(s.id, retireReason))}
                    className="rounded-lg border border-red-300 text-red-700 px-2 py-1 text-xs disabled:opacity-40" data-tour="counselling-retire">سحب</button>
          </div>
        )}
      </div>
    </aside>
  )
}

function Field({ label, value, onChange, disabled, area = false }) {
  const cls = 'mt-0.5 w-full rounded-lg border px-2 py-1.5 text-sm text-gray-900 disabled:bg-gray-50'
  return (
    <label className="block text-xs text-gray-500">{label}
      {area
        ? <textarea rows={2} value={value || ''} disabled={disabled} onChange={e => onChange(e.target.value)} className={cls} />
        : <input value={value || ''} disabled={disabled} onChange={e => onChange(e.target.value)} className={cls} />}
    </label>
  )
}
