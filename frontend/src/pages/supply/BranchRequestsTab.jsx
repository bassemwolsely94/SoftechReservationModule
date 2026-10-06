/**
 * BranchRequestsTab.jsx — /supply «طلبات واتساب»: urgent needs branches post in their
 * WhatsApp groups (the WhatsApp API cannot read groups, so the chat is pasted / a photo
 * uploaded).
 *
 *   paste → messages split → item lines matched to the catalog → review (one line at a time,
 *   Enter confirms) → availability analysis + Excel (the «تلبية طلبات الفروع» engine) →
 *   «إنشاء قائمة النواقص» creates the branch's shortage list and teaches the matcher.
 *
 * The backend (apps/supply/branch_requests.py) owns every rule — quantity reading, version
 * narrowing, flags. Versions of one product are never picked automatically. Nothing here
 * writes SOFTECH.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import { Chip, q, money, downloadBlob, inputCls, btnPrimary, btnGhost, fmtDate } from './supplyUi'
import { PlanView, PlanSettings, DEFAULT_SETTINGS, settingsBody, planBody, settingsChanged } from './IsrFulfilmentTab'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useBranchLabels from '../../hooks/useBranchLabels'
import ProgressBar from '../../components/ProgressBar'

const FLAG = {
  choose_variant:     ['اختر النوع / الحجم', 'amber'],
  qty_maybe_strength: ['الرقم قد يكون التركيز', 'rose'],
  qty_large:          ['كمية كبيرة', 'amber'],
  strength_mismatch:  ['التركيز غير موجود', 'rose'],
  head_mismatch:      ['اسم مختلف', 'rose'],
  low_score:          ['تطابق ضعيف', 'amber'],
  no_match:           ['لا يوجد تطابق', 'rose'],
  strips:             ['بالشريط', 'blue'],
  urgent:             ['مستعجل', 'violet'],
  ocr:                ['من صورة — راجِع', 'amber'],
  pack_not_found:     ['حجم العبوة غير موجود', 'amber'],
  learned_group:      ['من الذاكرة · عدة أصناف', 'teal'],
  learned_fuzzy:      ['من الذاكرة · تهجئة قريبة', 'teal'],
}
const NOTE = { phone: 'هاتف', name: 'اسم عميل', ref: 'مرجع', remark: 'ملاحظة' }
const STATUS_TONE = { draft: 'amber', confirmed: 'emerald', cancelled: 'gray' }

function errOf(e, fb = 'تعذّر تنفيذ العملية') { return e?.response?.data?.detail || fb }

export default function BranchRequestsTab() {
  const [selected, setSelected] = useState(null)        // request id, or null = new
  const listQ = useQuery({ queryKey: ['branch-requests'], queryFn: () => supplyApi.brList().then(r => r.data) })
  const list = listQ.data?.results || []
  return (
    <div className="space-y-4">
      <RequestList list={list} loading={listQ.isLoading} selected={selected} onSelect={setSelected} />
      {selected
        ? <Review key={selected} id={selected} />
        : <NewRequest branches={listQ.data?.branches || []} canWrite={!!listQ.data?.can_write}
            onCreated={(id) => setSelected(id)} />}
    </div>
  )
}

function RequestList({ list, loading, selected, onSelect }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="rounded-lg border border-line">
      <div className="flex items-center gap-2 px-3 py-2 bg-surface-2">
        <button onClick={() => setOpen(o => !o)} className="text-sm font-medium text-content">
          {open ? '▾' : '▸'} الطلبات السابقة ({list.length})
        </button>
        <button onClick={() => onSelect(null)} className={`${btnPrimary} ms-auto`}>+ طلب جديد</button>
      </div>
      {open && (
        <div className="max-h-56 overflow-y-auto">
          {loading && <p className="p-3 text-sm text-content/60">جاري التحميل…</p>}
          {!loading && list.length === 0 && <p className="p-3 text-sm text-content/60">لا توجد طلبات بعد.</p>}
          {list.length > 0 && (
            <table className="w-full text-sm">
              <thead className="text-xs text-content/60 sticky top-0 bg-surface">
                <tr>{['#', 'الفرع', 'المجموعة', 'الحالة', 'أصناف', 'مؤكَّد', 'للمراجعة', 'بواسطة', 'التاريخ'].map(h =>
                  <th key={h} className="px-2 py-1.5 font-medium text-center">{h}</th>)}</tr>
              </thead>
              <tbody>
                {list.map(r => (
                  <tr key={r.id} onClick={() => onSelect(r.id)}
                    className={`border-t border-line text-center cursor-pointer hover:bg-surface-2 ${selected === r.id ? 'bg-primary/5' : ''}`}>
                    <td className="px-2 py-1 font-mono">WA-{r.id}</td>
                    <td className="px-2 py-1">{r.branch} <span className="text-xs text-content/50">{r.branch_name}</span></td>
                    <td className="px-2 py-1 text-xs">{r.group_name || '—'}</td>
                    <td className="px-2 py-1"><Chip tone={STATUS_TONE[r.status]}>{r.status_label}</Chip></td>
                    <td className="px-2 py-1">{r.items}</td>
                    <td className="px-2 py-1">{r.confirmed}</td>
                    <td className="px-2 py-1">{r.need_review || '—'}</td>
                    <td className="px-2 py-1 text-xs whitespace-nowrap">{r.created_by || '—'}</td>
                    <td className="px-2 py-1 text-xs">{fmtDate(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

function NewRequest({ branches, canWrite, onCreated }) {
  const qc = useQueryClient()
  const [branch, setBranch] = useState('')
  const [group, setGroup] = useState('')
  const [text, setText] = useState('')
  const createM = useMutation({
    mutationFn: () => supplyApi.brCreate({ branch, group_name: group, text }).then(r => r.data),
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ['branch-requests'] }); onCreated(d.id) },
  })
  if (!canWrite) return <p className="text-sm text-content/60">يتطلب صلاحية التوريد لإدخال طلبات الفروع.</p>
  return (
    <div className="rounded-lg border border-line p-3 space-y-3">
      <div className="flex flex-wrap gap-3 items-end">
        <label className="flex flex-col gap-1 text-xs text-content/70">
          الفرع
          <select value={branch} onChange={e => setBranch(e.target.value)} className={inputCls}>
            <option value="">— اختر —</option>
            {branches.map(b => <option key={b.code} value={b.code}>{b.code} · {b.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-content/70 grow min-w-[14rem]">
          اسم المجموعة (اختياري)
          <input value={group} onChange={e => setGroup(e.target.value)} className={inputCls}
            placeholder="طلبات مستعجلة - النزهه" />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-xs text-content/70">
        رسائل المجموعة
        <textarea value={text} onChange={e => setText(e.target.value)} rows={10} dir="auto"
          className={`${inputCls} font-mono text-[13px] leading-6`}
          placeholder={'في واتساب على الكمبيوتر: حدِّد الرسائل (⋮ ← تحديد الرسائل) ثم نسخ، والصقها هنا.\nأو الصق نص الرسائل مباشرة — سطر لكل صنف.'} />
      </label>
      <div className="flex items-center gap-3">
        <button onClick={() => createM.mutate()} disabled={!branch || !text.trim() || createM.isPending} className={btnPrimary}>
          {createM.isPending ? 'جاري الاستخراج والمطابقة…' : 'استخراج الأصناف'}
        </button>
        {createM.isError && <span className="text-sm text-rose-700">{errOf(createM.error)}</span>}
        <span className="text-xs text-content/50">الرقم بعد اسم الصنف = التركيز. الكمية فقط مع: علبة / علب / box / عدد / شريط / ×</span>
      </div>
    </div>
  )
}

function Review({ id }) {
  const bl = useBranchLabels()
  const qc = useQueryClient()
  const [detail, setDetail] = useState(null)
  const [msg, setMsg] = useState('')
  const [plan, setPlan] = useState(null)
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const [moreText, setMoreText] = useState('')
  const [showMore, setShowMore] = useState(false)
  const fileRef = useRef(null)
  const getQ = useQuery({ queryKey: ['branch-request', id], queryFn: () => supplyApi.brGet(id).then(r => r.data) })
  useEffect(() => { if (getQ.data) setDetail(getQ.data) }, [getQ.data])

  const refreshList = () => qc.invalidateQueries({ queryKey: ['branch-requests'] })
  const act = (fn, after) => ({
    mutationFn: fn,
    onMutate: () => setMsg(''),
    onSuccess: (res) => { const d = res.data; setDetail(d); refreshList(); after?.(d) },
    onError: (e) => setMsg(errOf(e)),
  })
  const lineM = useMutation(act(({ lid, data }) => supplyApi.brLine(id, lid, data)))
  const safeM = useMutation(act(() => supplyApi.brConfirmSafe(id), d => setMsg(`تم تأكيد ${d.confirmed_now} سطر آمن.`)))
  const confirmM = useMutation(act(() => supplyApi.brConfirm(id),
    d => setMsg(`تم إنشاء قائمة نواقص فرع ${bl(d.branch)} (${d.shortage_list_items} صنف).`)))
  const cancelM = useMutation(act(() => supplyApi.brCancel(id)))
  const textM = useMutation(act(() => supplyApi.brText(id, moreText), () => { setMoreText(''); setShowMore(false) }))
  const ocrM = useMutation(act((file) => supplyApi.brOcr(id, file)))
  const analysisM = useMutation({
    mutationFn: (extra) => supplyApi.brAnalysis(id, { ...settingsBody(settings), token: plan?.token, ...extra }).then(r => r.data),
    onMutate: () => setMsg(''),
    onSuccess: setPlan,
    onError: (e) => setMsg(errOf(e)),
  })
  const exportM = useMutation({
    mutationFn: () => supplyApi.brExport(id, { ...settingsBody(settings), token: plan?.token }),
    onSuccess: (res) => {
      const m = (res.headers?.['content-disposition'] || '').match(/filename="?([^"]+)"?/)
      downloadBlob(res.data, m ? m[1] : `whatsapp_request_${id}.xlsx`)
    },
    onError: () => setMsg('تعذّر التصدير'),
  })

  const groups = useMemo(() => {
    const g = new Map()
    for (const l of detail?.lines || []) {
      if (!g.has(l.msg_index)) g.set(l.msg_index, { sender: l.msg_sender, time: l.msg_time, ocr: l.from_ocr, lines: [] })
      g.get(l.msg_index).lines.push(l)
    }
    return [...g.values()]
  }, [detail])

  // keyboard flow (shared with every review grid): rows in screen order, items only
  const kbRows = useMemo(() => groups.flatMap(g => g.lines).filter(l => l.kind === 'item'), [groups])
  const [openReq, setOpenReq] = useState(null)      // {id, n}: M toggles that line's picker
  const canEdit = detail?.status === 'draft' && detail?.can_write
  const kb = useGridKeyboard({
    rows: kbRows, getKey: l => l.id, enabled: !!canEdit, advanceOnConfirm: true,
    onConfirm: l => { if (l.item && !l.confirmed) lineM.mutate({ lid: l.id, data: { confirmed: true } }) },
    onToggle: l => { if (l.item) lineM.mutate({ lid: l.id, data: { confirmed: !l.confirmed } }) },
    onOpen: l => setOpenReq(r => ({ id: l.id, n: (r?.n || 0) + 1 })),
  })

  if (getQ.isLoading || !detail) return <p className="text-sm text-content/60">جاري التحميل…</p>
  const draft = detail.status === 'draft'
  const editable = draft && detail.can_write
  const items = detail.lines.filter(l => l.kind === 'item')
  const pending = items.filter(l => !l.confirmed)
  const busy = lineM.isPending

  const update = (lid, data) => lineM.mutate({ lid, data })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2 bg-surface-2">
        <h3 className="font-semibold text-content">طلب WA-{detail.id} — فرع {detail.branch} {detail.branch_name}</h3>
        {detail.group_name && <span className="text-xs text-content/60">{detail.group_name}</span>}
        <Chip tone={STATUS_TONE[detail.status]}>{detail.status_label}</Chip>
        <span className="text-xs text-content/60">{items.length} صنف · {items.length - pending.length} مؤكَّد · {pending.length} للمراجعة</span>
        {detail.shortage_list_id && <Chip tone="emerald">قائمة النواقص #{detail.shortage_list_id}</Chip>}
        <div className="ms-auto flex flex-wrap gap-2">
          {editable && <>
            <button className={btnGhost} onClick={() => setShowMore(s => !s)}>+ رسائل</button>
            <button className={btnGhost} onClick={() => fileRef.current?.click()} disabled={ocrM.isPending}>
              {ocrM.isPending ? 'جاري قراءة الصورة…' : '+ صورة'}
            </button>
            <input ref={fileRef} type="file" accept="image/*" hidden
              onChange={e => { const f = e.target.files?.[0]; if (f) ocrM.mutate(f); e.target.value = '' }} />
            <button className={btnGhost} onClick={() => safeM.mutate()} disabled={safeM.isPending}
              title="يؤكّد كل سطر مطابق بلا تنبيهات وبنسبة تطابق جيدة">تأكيد الآمنة</button>
            <button className={btnPrimary} onClick={() => confirmM.mutate()}
              disabled={confirmM.isPending || items.length === pending.length}
              title="ينشئ قائمة نواقص الفرع من الأسطر المؤكَّدة ويُعلِّم المطابِق">
              {confirmM.isPending ? '…' : `إنشاء قائمة النواقص (${items.length - pending.length})`}
            </button>
            <button className="text-xs text-rose-700 underline" onClick={() => cancelM.mutate()}>إلغاء الطلب</button>
          </>}
        </div>
      </div>
      {msg && <div className="text-sm rounded border border-line bg-surface p-2">{msg}</div>}
      {showMore && editable && (
        <div className="flex gap-2 items-start">
          <textarea value={moreText} onChange={e => setMoreText(e.target.value)} rows={4} dir="auto"
            className={`${inputCls} grow font-mono text-[13px]`} placeholder="رسائل إضافية من نفس المجموعة" />
          <button className={btnPrimary} onClick={() => textM.mutate()} disabled={!moreText.trim() || textM.isPending}>إضافة</button>
        </div>
      )}
      {editable && pending.length > 0 && (
        <p className="text-xs text-content/50">راجِع كل سطر: اختر النوع عند الحاجة وعدِّل الكمية، ثم Enter للتأكيد والانتقال للسطر التالي.
          <span className="ms-2 text-content/40">⌨ ↑↓ تنقل · Enter تأكيد والتالي · مسافة إلغاء/تأكيد · M تغيير الصنف</span></p>
      )}

      <div {...kb.containerProps} className={`rounded-lg border border-line divide-y divide-line ${kb.containerProps.className}`}>
        {groups.map((g, gi) => (
          <div key={gi}>
            <div className="px-3 py-1.5 text-xs text-content/60 bg-surface-2/60 flex gap-2">
              <span className="font-medium">{g.sender || 'رسالة'}</span>
              {g.time && <span>{g.time}</span>}
              {g.ocr && <Chip tone="amber">من صورة</Chip>}
            </div>
            {g.lines.map(l => (
              <Line key={l.id} l={l} reqId={id} editable={editable} busy={busy} update={update}
                kb={l.kind === 'item' ? kb.rowProps(l, { block: true }) : null} openReq={openReq} />
            ))}
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-line p-3 space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <h4 className="font-semibold text-content">تحليل التوفير</h4>
          <span className="text-xs text-content/50">
            نفس تحليل «تلبية طلبات الفروع»: الرئيسي وحده إذا كان يكفي، وإلا فائض الفروع الأخرى ← الرئيسي ← النقص.
            يشمل الأسطر المؤكَّدة والمطابقات الآمنة فقط — الأسطر التي تحتاج اختياراً لا تدخل الحساب حتى تُراجَع.
          </span>
          <div className="flex flex-wrap items-end gap-3 ms-auto">
            <PlanSettings value={settings} onChange={setSettings} />
          </div>
          <button className={btnPrimary} onClick={() => analysisM.mutate({})} disabled={analysisM.isPending}>
            {analysisM.isPending ? 'جاري التحليل…' : 'تحليل'}
          </button>
          {plan && <>
            <button className={btnGhost} onClick={() => analysisM.mutate({ refresh: true })} disabled={analysisM.isPending}>تحديث من SOFTECH</button>
            <button className={btnGhost} onClick={() => exportM.mutate()} disabled={exportM.isPending}>
              {exportM.isPending ? 'جاري التصدير…' : 'تصدير Excel'}
            </button>
          </>}
        </div>
        {analysisM.isPending && <ProgressBar since={analysisM.submittedAt} label="قراءة الأرصدة من سيرفرات الفروع"
          message="سيرفر بطيء أو متوقف يُستبدل بنسخة الرئيسي تلقائياً — قد يستغرق دقيقة" />}
        {exportM.isPending && <ProgressBar since={exportM.submittedAt} label="تجهيز ملف Excel" />}
        {plan && <TransfersBar id={id} plan={plan} setPlan={setPlan} disabled={detail.status === 'cancelled'} />}
        {plan && <PlanView plan={plan} setPlan={setPlan} isrText=""
          coverageChanged={settingsChanged(settings, plan)} />}
      </div>
    </div>
  )
}

const LEG_TONE = { proposed: 'amber', approved: 'blue', pushed: 'emerald', failed: 'rose', cancelled: 'gray' }

// «from other branches» → two linked transfer proposals per donor (donor → 100 → branch).
// PG only: they land in «طلبات التوريد / ISR» as مقترح and reach SOFTECH only through the
// usual اعتماد → ترحيل there.
function TransfersBar({ id, plan, setPlan, disabled }) {
  const bl = useBranchLabels()
  const [, setParams] = useSearchParams()
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')
  const r = plan.isrs?.[0]
  const transfers = plan.transfers || []
  const live = new Set(transfers.filter(t => t.legs.some(l => ['proposed', 'approved', 'pushed'].includes(l.status)))
    .map(t => t.donor))
  const pending = Object.entries(r?.from_by_donor || {}).filter(([b]) => !live.has(b))
  const pendingQty = pending.reduce((s, [, v]) => s + v, 0)
  const createM = useMutation({
    mutationFn: () => supplyApi.brTransfers(id, planBody(plan)).then(res => res.data),
    onMutate: () => setMsg(''),
    onSuccess: (d) => {
      setPlan(d.plan)
      qc.invalidateQueries({ queryKey: ['isr-pushes'] })
      setMsg(d.created.length
        ? `تم إنشاء ${d.created.length} تحويل (${d.created.length * 2} طلب توريد مقترح): `
          + d.created.map(c => `فرع ${bl(c.donor)} ← ${bl('100')} ← فرع ${bl(r.branch)}: ${q(c.qty)}`).join(' · ')
          + '. راجعها واعتمدها في تبويب طلبات التوريد.'
        : 'لم يُنشأ شيء — لا يوجد فائض جديد بعد إعادة قراءة الأرصدة، أو التحويلات موجودة بالفعل.')
    },
    onError: (e) => setMsg(errOf(e, 'تعذّر إنشاء التحويلات')),
  })
  if (!r || (!transfers.length && !pending.length)) return null
  return (
    <div className="rounded border border-line bg-surface-2/60 px-3 py-2 flex flex-wrap items-center gap-2 text-xs">
      <span className="text-content/70">التحويل من فائض الفروع (فرع ← الرئيسي ← فرع {bl(r.branch)}):</span>
      {transfers.map(t => (
        <span key={t.donor} className="inline-flex items-center gap-1">
          <span className="font-medium">فرع {bl(t.donor)}:</span>
          {t.legs.map(l => (
            <Chip key={l.id} tone={LEG_TONE[l.status] || 'gray'}
              title={l.isrdocnumber ? `SOFTECH ISR ${l.isrdocnumber}` : ''}>
              {l.kind === 'branch_to_hq' ? `${bl(t.donor)} ⟶ ${bl('100')}` : `${bl('100')} ⟶ ${bl(r.branch)}`} · {q(l.qty)} · #{l.id} {l.status_label}
            </Chip>
          ))}
        </span>
      ))}
      {pending.length > 0 && plan.can_transfer && !disabled && (
        <button onClick={() => createM.mutate()} disabled={createM.isPending} className={btnPrimary}
          title="لكل فرع مانح: طلب توريد من الفرع إلى الرئيسي + طلب من الرئيسي إلى الفرع الطالب — من الأسطر المؤكَّدة فقط، بعد إعادة قراءة الأرصدة">
          {createM.isPending ? 'جاري الإنشاء…' : `إنشاء مقترحات التحويل (${q(pendingQty)} من ${pending.length} فرع)`}
        </button>
      )}
      {transfers.length > 0 && (
        <button onClick={() => setParams(p => { const n = new URLSearchParams(p); n.set('tab', 'isr'); return n })}
          className="text-primary underline">فتح تبويب طلبات التوريد</button>
      )}
      {msg && <span className="basis-full text-content/80">{msg}</span>}
    </div>
  )
}

function Line({ l, reqId, editable, busy, update, kb, openReq }) {
  const needsChoice = !l.item || (l.flags || []).some(f => ['choose_variant', 'low_score', 'head_mismatch',
    'strength_mismatch', 'no_match'].includes(f))
  const [open, setOpen] = useState(l.kind === 'item' && !l.confirmed && needsChoice)
  const [qtyDraft, setQtyDraft] = useState(String(l.qty))
  useEffect(() => setQtyDraft(String(l.qty)), [l.qty])
  useEffect(() => { if (openReq?.id === l.id) setOpen(o => !o) }, [openReq, l.id])   // M key

  if (l.kind === 'note') {
    return (
      <div className="px-3 py-1 flex items-center gap-2 text-xs text-content/50">
        <span className="w-16 shrink-0">{NOTE[(l.flags || [])[0]] || 'ملاحظة'}</span>
        <span dir="auto" className="grow">{l.raw_text}</span>
        {editable && <button className="underline" onClick={() => update(l.id, { kind: 'item' })}>صنف؟</button>}
      </div>
    )
  }
  const saveQty = () => {
    const v = Number(qtyDraft)
    if (v > 0 && v !== l.qty) update(l.id, { qty: v })
  }
  const flags = (l.flags || []).filter(f => FLAG[f])
  return (
    <div ref={kb?.ref} onMouseDown={kb?.onMouseDown} data-kb-active={kb?.['data-kb-active']}
      className={`px-3 py-2 ${l.confirmed ? 'bg-emerald-50/40' : ''} ${kb?.className || ''}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span dir="auto" className="text-sm text-content/80 min-w-[10rem] max-w-[22rem] truncate" title={l.raw_text}>{l.raw_text}</span>
        <span className="text-content/30">←</span>
        <div className="grow min-w-[14rem]">
          {l.item ? (
            <span className="text-sm">
              {(l.picks?.length > 1 ? l.picks : [l.item]).map((p, i) => (
                <span key={p.id} className="me-2 inline-block">
                  {i > 0 && <span className="text-content/40 me-1">+</span>}
                  <span className="font-mono text-xs text-content/50 me-1">{p.code}</span>{p.name}
                </span>
              ))}
              {l.picks?.length > 1 && <Chip tone="teal">{l.picks.length} أصناف · الكمية لكل صنف</Chip>}
              {l.all_variants && <Chip tone="teal">كل الأنواع</Chip>}
            </span>
          ) : <span className="text-sm text-amber-700">اختر الصنف</span>}
          <div className="flex flex-wrap gap-1 mt-0.5">
            {flags.map(f => <Chip key={f} tone={FLAG[f][1]}>{FLAG[f][0]}</Chip>)}
            {l.pack_hint && (
              <Chip tone="blue" title="العبوة المكتوبة غير موجودة بالكتالوج — اقتراح فقط، الكمية لا تتغير تلقائياً">
                {l.pack_hint.written} قرص ≈ {l.pack_hint.packs} علب × {l.pack_hint.per_pack}
                {editable && Number(l.qty) !== l.pack_hint.packs && (
                  <button className="underline ms-1" onClick={() => update(l.id, { qty: l.pack_hint.packs })}>
                    اعتمد {l.pack_hint.packs}
                  </button>
                )}
              </Chip>
            )}
            {l.item && <span className="text-[11px] text-content/50">
              رصيد الفرع {l.item.branch_stock == null ? '—' : q(l.item.branch_stock)} · مبيعات الشبكة {q(l.item.network_rate)}/شهر
            </span>}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <input type="number" min="1" step="1" value={qtyDraft} disabled={!editable}
            onChange={e => setQtyDraft(e.target.value)} onBlur={saveQty}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); saveQty() } }}
            className={`${inputCls} w-16 text-center`} title={`الكمية (${l.qty_source === 'default' ? 'افتراضية' : l.qty_source === 'manual' ? 'معدَّلة' : 'من النص'})`} />
          <select value={l.qty_unit} disabled={!editable} onChange={e => update(l.id, { qty_unit: e.target.value })}
            className={`${inputCls} py-1`}>
            <option value="pack">علبة</option><option value="strip">شريط</option>
          </select>
          {l.qty_unit === 'strip' && l.packs != null && <span className="text-[11px] text-content/50">= {q(l.packs)} علبة</span>}
        </div>
        {editable && (
          <div className="flex items-center gap-1">
            <button className="text-xs underline text-content/60" onClick={() => setOpen(o => !o)}>{open ? 'إخفاء' : 'تغيير'}</button>
            <button className="text-xs underline text-content/50" onClick={() => update(l.id, { kind: 'note' })}>ليس صنفاً</button>
            <button disabled={!l.item || busy}
              onClick={() => update(l.id, { confirmed: !l.confirmed })}
              className={`text-xs px-2 py-1 rounded border ${l.confirmed ? 'bg-emerald-600 text-white border-emerald-600' : 'border-line text-content'} disabled:opacity-40`}>
              {l.confirmed ? '✓ مؤكَّد' : 'تأكيد'}
            </button>
          </div>
        )}
        {!editable && l.confirmed && <Chip tone="emerald">✓</Chip>}
      </div>
      {open && editable && <Choices l={l} reqId={reqId} update={update} busy={busy} />}
    </div>
  )
}

function Choices({ l, reqId, update, busy }) {
  const [term, setTerm] = useState('')
  const [results, setResults] = useState(null)
  const searchM = useMutation({
    mutationFn: () => supplyApi.brSearch(reqId, l.id, term).then(r => r.data.results),
    onSuccess: setResults,
  })
  const list = results || l.candidates || []
  const variants = (l.candidates || []).filter(c => c.variant).length
  const pickIds = (l.picks || []).map(p => p.id)
  // ONE control: tick = add to this line, untick = remove. Several ticks = several items,
  // each with the line's quantity. «فقط هذا» replaces the selection in one click.
  const setPicks = (ids) => update(l.id, { item_ids: ids })
  const togglePick = (cid) => setPicks(pickIds.includes(cid) ? pickIds.filter(x => x !== cid) : [...pickIds, cid])
  return (
    <div className="mt-2 ms-4 rounded border border-line bg-surface p-2 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-content/60">المختار لهذا السطر:</span>
        {(l.picks || []).length === 0 && <span className="text-amber-700">لا شيء بعد — علِّم صنفاً أو أكثر من القائمة</span>}
        {(l.picks || []).map(p => (
          <span key={p.id} className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/5 px-2 py-0.5">
            <span className="font-mono text-content/50">{p.code}</span>{p.name}
            <button disabled={busy} onClick={() => togglePick(p.id)} title="إزالة"
              className="text-content/50 hover:text-rose-700 disabled:opacity-40">✕</button>
          </span>
        ))}
        {(l.picks || []).length > 1 && <span className="text-content/50">· الكمية ({q(l.qty)}) لكل صنف</span>}
        {busy && <span className="text-content/50 ms-auto">جاري الحفظ…</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input value={term} onChange={e => setTerm(e.target.value)} dir="auto" placeholder="ابحث باسم آخر أو بالكود"
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); if (term.trim()) searchM.mutate() } }}
          className={`${inputCls} w-64`} />
        <button className={btnGhost} onClick={() => searchM.mutate()} disabled={!term.trim() || searchM.isPending}>بحث</button>
        {results && <button className="text-xs underline" onClick={() => setResults(null)}>الاقتراحات</button>}
        {variants > 1 && (
          <label className="flex items-center gap-1 text-xs ms-auto">
            <input type="checkbox" checked={l.all_variants} disabled={busy}
              onChange={e => update(l.id, { all_variants: e.target.checked })} />
            كل الأنواع ({variants})
          </label>
        )}
      </div>
      <table className="w-full text-xs">
        <thead className="text-content/50">
          <tr>
            <th className="px-2 py-1 font-medium text-center" title="علِّم صنفاً أو أكثر — كل صنف بكمية السطر">اختيار</th>
            {['الكود', 'الصنف', 'رصيد الفرع', 'مبيعات الشبكة/شهر', 'السعر', 'تطابق', ''].map((h, i) =>
              <th key={i} className="px-2 py-1 font-medium text-center">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {list.map(c => {
            const picked = pickIds.includes(c.id)
            return (
              <tr key={c.id} onClick={() => !busy && togglePick(c.id)}
                className={`border-t border-line text-center cursor-pointer hover:bg-surface-2 ${picked ? 'bg-primary/10' : ''}`}>
                <td className="px-2 py-1">
                  <input type="checkbox" checked={picked} disabled={busy} readOnly
                    className="h-4 w-4 accent-[rgb(var(--c-brand-600))] pointer-events-none"
                    aria-label={picked ? 'إزالة' : 'اختيار'} />
                </td>
                <td className="px-2 py-1 font-mono">{c.code}</td>
                <td className="px-2 py-1 text-start">
                  {c.name}
                  {c.variant && !results && <span className="ms-1 text-teal-700">•</span>}
                </td>
                <td className="px-2 py-1">{c.branch_stock == null ? '—' : q(c.branch_stock)}</td>
                <td className="px-2 py-1">
                  {c.network_rate > 0 ? q(c.network_rate) : <Chip tone="gray" title="لا مبيعات في الشبكة — قد يكون كوداً قديماً مكرراً">لا مبيعات</Chip>}
                </td>
                <td className="px-2 py-1">{c.pack_price ? money(c.pack_price) : '—'}</td>
                <td className="px-2 py-1">{c.score == null ? '—' : `${Math.round(c.score * 100)}%`}</td>
                <td className="px-2 py-1">
                  {!(picked && pickIds.length === 1) && (
                    <button disabled={busy} title="اختيار هذا الصنف وحده بدل المختار"
                      onClick={(e) => { e.stopPropagation(); setPicks([c.id]) }}
                      className="text-[11px] underline text-content/60 hover:text-primary disabled:opacity-40">فقط هذا</button>
                  )}
                </td>
              </tr>
            )
          })}
          {list.length === 0 && <tr><td colSpan={8} className="px-2 py-2 text-center text-content/50">لا نتائج — جرّب البحث باسم أو كود.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}
