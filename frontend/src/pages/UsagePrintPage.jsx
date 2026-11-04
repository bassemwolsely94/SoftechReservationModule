/**
 * pages/UsagePrintPage.jsx — «طريقة الاستخدام»: print how-to-use instructions for a sale on the
 * receipt printer (Project 5).
 *
 * Type the invoice number → its lines appear with a suggested instruction each (the source is
 * shown). The pharmacist edits / builds it from quick chips, confirms every line (or «لا يطبع»),
 * then prints. All rules live on the server (apps/usage_print): suggestions, the
 * "every line decided" print lock, audit. This page only shows and sends decisions.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { usagePrintApi, branchesApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import useAuthStore from '../store/authStore'
import { printUsageSlip } from '../components/UsageSlipPrint'

const errText = (e) => e?.response?.data?.detail || 'حدث خطأ — حاول مرة أخرى.'

// One quiet status line instead of popups (calm UI): ok / error, fades after a few seconds.
function useNotice() {
  const [notice, setNotice] = useState(null)
  useEffect(() => {
    if (!notice) return undefined
    const t = setTimeout(() => setNotice(null), 5000)
    return () => clearTimeout(t)
  }, [notice])
  const show = { ok: (text) => setNotice({ ok: true, text }), error: (text) => setNotice({ ok: false, text }) }
  const bar = notice && (
    <div className={`rounded-lg px-3 py-2 text-sm ${notice.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'}`}>
      {notice.text}
    </div>
  )
  return [bar, show]
}
const isoDay = (d) => {
  const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
  return z.toISOString().slice(0, 10)
}
const TABS = [
  { key: 'print', label: '🏷️ الطباعة' },
  { key: 'settings', label: '⚙️ القوالب والإعدادات' },
]
const SOURCE_STYLE = {
  patient_last: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  item_common: 'bg-blue-50 text-blue-700 border-blue-200',
  curated: 'bg-violet-50 text-violet-700 border-violet-200',
  none: 'bg-gray-50 text-gray-500 border-gray-200',
}
const CHIP_ROWS = [['amount', 'الكمية'], ['frequency', 'المرات'], ['timing', 'التوقيت']]

// ── One invoice line ──────────────────────────────────────────────────────────

function LineRow({ line, presets, draft, setDraft, active, onFocus, onAction, busy, canAct }) {
  const inputRef = useRef(null)
  const pending = line.status === 'pending'
  const addChip = (t, replace) => {
    setDraft(replace ? t : [draft.trim(), t].filter(Boolean).join(' '))
    inputRef.current?.focus()
  }
  const tone = line.status === 'confirmed' ? 'border-emerald-300 bg-emerald-50/40'
    : line.status === 'excluded' ? 'border-gray-200 bg-gray-50 opacity-70' : 'border-amber-200 bg-white'
  return (
    <div className={`rounded-xl border p-3 ${tone}`} data-tour="usage-print-line">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-bold text-gray-900" dir="ltr">{line.item_name}</span>
        <span className="text-xs text-gray-500">× {Number(line.quantity)}</span>
        <span className={`text-[11px] px-2 py-0.5 rounded-full border ${SOURCE_STYLE[line.suggestion_source] || SOURCE_STYLE.none}`}>
          {line.suggestion_label}
        </span>
        {line.status === 'confirmed' && <span className="ms-auto text-xs text-emerald-700">✓ {line.confirmed_by}</span>}
        {line.status === 'excluded' && <span className="ms-auto text-xs text-gray-500">لا يطبع</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2 mt-2">
        <input ref={inputRef} value={draft} disabled={!pending || !canAct}
          onChange={e => setDraft(e.target.value)} onFocus={onFocus}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); onAction('confirm') } }}
          placeholder="اكتب طريقة الاستخدام أو اختار من الاختيارات تحت"
          className="flex-1 min-w-[16rem] border rounded-lg px-3 py-2 text-base disabled:bg-transparent disabled:border-transparent disabled:font-semibold"
          data-tour="usage-print-text" />
        {canAct && pending && <>
          <button disabled={busy} onClick={() => onAction('confirm')} data-tour="usage-print-confirm"
            className="px-3 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50">✓ تأكيد</button>
          <button disabled={busy} onClick={() => onAction('exclude')} data-tour="usage-print-exclude"
            className="px-3 py-2 rounded-lg border text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">لا يطبع</button>
        </>}
        {canAct && !pending &&
          <button disabled={busy} onClick={() => onAction('reset')} data-tour="usage-print-edit"
            className="px-3 py-2 rounded-lg border text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">تعديل</button>}
      </div>
      {canAct && pending && active && (
        <div className="mt-2 space-y-1" data-tour="usage-print-chips">
          {CHIP_ROWS.map(([kind, label]) => (presets[kind] || []).length > 0 && (
            <div key={kind} className="flex flex-wrap items-center gap-1">
              <span className="text-[11px] text-gray-400 w-14">{label}</span>
              {presets[kind].map(t => (
                <button key={t} onMouseDown={e => e.preventDefault()} onClick={() => addChip(t, false)}
                  className="text-xs px-2 py-1 rounded-full bg-gray-100 hover:bg-gray-200 text-gray-700">{t}</button>
              ))}
            </div>
          ))}
          {(presets.phrase || []).length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-[11px] text-gray-400 w-14">جاهز</span>
              {presets.phrase.map(t => (
                <button key={t} onMouseDown={e => e.preventDefault()} onClick={() => addChip(t, true)}
                  className="text-xs px-2 py-1 rounded-full bg-primary/10 hover:bg-primary/20 text-primary">{t}</button>
              ))}
              {draft && <button onMouseDown={e => e.preventDefault()} onClick={() => addChip('', true)}
                className="text-xs px-2 py-1 text-gray-400 hover:text-gray-600">مسح</button>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Prescription photo ────────────────────────────────────────────────────────

function Prescription({ sheet, canAct, onUploaded, toast }) {
  const fileRef = useRef(null)
  const [open, setOpen] = useState(false)
  const up = useMutation({
    mutationFn: (f) => usagePrintApi.prescription(sheet.id, f).then(r => r.data),
    onSuccess: (d) => { onUploaded(d); toast.ok('تم إرفاق صورة الروشتة') },
    onError: (e) => toast.error(errText(e)),
  })
  return (
    <div className="flex items-center gap-2" data-tour="usage-print-rx">
      {sheet.prescription_image ? (
        <>
          <button onClick={() => setOpen(true)} className="block">
            <img src={sheet.prescription_image} alt="الروشتة" className="h-14 w-14 object-cover rounded-lg border" />
          </button>
          <span className="text-xs text-gray-500">{sheet.prescription_origin === 'pos' ? 'من أمر نقطة البيع' : 'مرفقة هنا'}</span>
        </>
      ) : canAct && (
        <button onClick={() => fileRef.current?.click()} disabled={up.isPending}
          className="text-sm px-3 py-2 rounded-lg border border-dashed text-gray-600 hover:bg-gray-50">
          {up.isPending ? 'جاري الرفع…' : '📷 إرفاق صورة الروشتة'}
        </button>
      )}
      <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = '' }} />
      {open && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={() => setOpen(false)}>
          <img src={sheet.prescription_image} alt="الروشتة" className="max-h-full max-w-full rounded-lg" />
        </div>
      )}
    </div>
  )
}

// ── Print tab ─────────────────────────────────────────────────────────────────

function PrintTab() {
  const user = useAuthStore(s => s.user)
  const [noticeBar, toast] = useNotice()
  const [form, setForm] = useState({ number: '', date: isoDay(new Date()), branch: '' })
  const [query, setQuery] = useState(null)
  const [sheet, setSheet] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [active, setActive] = useState(null)
  const [layout, setLayout] = useState('single')
  const numberRef = useRef(null)
  const branches = useQuery({
    queryKey: ['branch-labels'], staleTime: 30 * 60 * 1000,
    queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
  })
  const branchRows = (Array.isArray(branches.data) ? branches.data : branches.data?.results || [])
    .filter(b => b.is_active !== false)

  const load = useQuery({
    queryKey: ['usage-print', 'sheet', query], enabled: !!query, retry: false, staleTime: 0,
    queryFn: () => usagePrintApi.sheet(query).then(r => r.data),
  })
  useEffect(() => {
    if (!load.data) return
    setSheet(load.data)
    setDrafts(Object.fromEntries(load.data.lines.map(l => [l.id, l.text])))
    setActive(load.data.lines.find(l => l.status === 'pending')?.id ?? null)
  }, [load.data])

  const apply = (data) => {
    setSheet(data)
    setDrafts(d => Object.fromEntries(data.lines.map(l => [l.id, l.status === 'pending' ? (d[l.id] ?? l.text) : l.text])))
  }
  const act = useMutation({
    mutationFn: ({ line, action }) => usagePrintApi.line(line.id, { action, text: drafts[line.id] || '' }).then(r => r.data),
    onSuccess: (data, { line, action }) => {
      apply(data)
      if (action !== 'reset') {
        const next = data.lines.find(l => l.status === 'pending' && l.id !== line.id)
        setActive(next?.id ?? null)
      } else setActive(line.id)
    },
    onError: (e) => toast.error(errText(e)),
  })
  const print = useMutation({
    mutationFn: () => usagePrintApi.print(sheet.id, layout).then(r => r.data),
    onSuccess: (d) => {
      apply(d.sheet)
      if (!printUsageSlip(d.slip)) toast.error('المتصفح منع نافذة الطباعة — اسمح بالنوافذ المنبثقة لهذا الموقع.')
    },
    onError: (e) => toast.error(errText(e)),
  })

  const open = (e) => {
    e?.preventDefault()
    if (!form.number.trim()) return numberRef.current?.focus()
    setSheet(null)
    setQuery({ number: form.number.trim(), date: form.date, branch: form.branch })
  }
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'F9' && sheet?.ready && sheet.perms.can_create && !print.isPending) { e.preventDefault(); print.mutate() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sheet, print])

  const pendingCount = sheet ? sheet.lines.filter(l => l.status === 'pending').length : 0
  const canAct = !!sheet?.perms?.can_create

  return (
    <div className="space-y-4">
      <form onSubmit={open} className="flex flex-wrap items-end gap-2 bg-white rounded-xl border p-3" data-tour="usage-print-find">
        <label className="flex flex-col text-xs text-gray-500">رقم الفاتورة
          <input ref={numberRef} autoFocus inputMode="numeric" value={form.number}
            onChange={e => setForm(f => ({ ...f, number: e.target.value.replace(/[^\d]/g, '') }))}
            className="mt-1 w-40 border rounded-lg px-3 py-2 text-lg text-gray-900" data-tour="usage-print-number" />
        </label>
        <label className="flex flex-col text-xs text-gray-500">التاريخ
          <input type="date" value={form.date} max={isoDay(new Date())}
            onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
            className="mt-1 border rounded-lg px-3 py-2 text-gray-900" />
        </label>
        <label className="flex flex-col text-xs text-gray-500">الفرع
          <select value={form.branch} onChange={e => setForm(f => ({ ...f, branch: e.target.value }))}
            className="mt-1 border rounded-lg px-3 py-2 text-gray-900 min-w-[12rem]">
            <option value="">فرعي{user?.branch_name ? ` — ${user.branch_name}` : ''}</option>
            {branchRows.map(b => (
              <option key={b.id} value={b.softech_branch_id}>{b.softech_branch_id} · {b.name_ar || b.name}</option>
            ))}
          </select>
        </label>
        <button type="submit" className="px-5 py-2 rounded-lg bg-primary text-white font-medium hover:opacity-90"
          data-tour="usage-print-open">فتح الفاتورة</button>
        {load.isFetching && <span className="text-sm text-gray-400">جاري البحث…</span>}
      </form>

      {noticeBar}
      {load.isError && !load.isFetching && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 text-amber-800 p-3 text-sm">{errText(load.error)}</div>
      )}

      {sheet && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 bg-white rounded-xl border p-3">
            <div>
              <div className="font-bold text-gray-900">فاتورة {sheet.docnumber}
                <span className="text-sm font-normal text-gray-500"> · {sheet.branch.code} · {sheet.branch.name} · {sheet.docdate}</span></div>
              <div className="text-sm text-gray-600">{sheet.patient_name || 'عميل بدون اسم — لن يُطبع اسم'}
                {sheet.source === 'live' && <span className="text-xs text-gray-400"> · قراءة مباشرة من SOFTECH</span>}
                {sheet.print_count > 0 && <span className="text-xs text-gray-400"> · طُبعت {sheet.print_count} مرة</span>}</div>
            </div>
            <div className="ms-auto"><Prescription sheet={sheet} canAct={canAct} onUploaded={apply} toast={toast} /></div>
          </div>

          {sheet.invoice_changed && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 text-amber-800 p-3 text-sm">
              الفاتورة اتغيرت من آخر مرة — الأصناف الجديدة أو اللي اتغيرت كميتها محتاجة تأكيد تاني.
            </div>
          )}

          {sheet.lines.map(line => (
            <LineRow key={line.id} line={line} presets={sheet.presets} canAct={canAct}
              draft={drafts[line.id] ?? ''} setDraft={(v) => setDrafts(d => ({ ...d, [line.id]: v }))}
              active={active === line.id} onFocus={() => setActive(line.id)}
              busy={act.isPending} onAction={(action) => act.mutate({ line, action })} />
          ))}

          <div className="sticky bottom-0 flex flex-wrap items-center gap-3 bg-white/95 backdrop-blur rounded-xl border p-3" data-tour="usage-print-bar">
            <div className="flex gap-1 bg-gray-100 rounded-lg p-1" data-tour="usage-print-layout">
              {[['single', 'ورقة واحدة'], ['per_item', 'قطعة لكل صنف']].map(([k, label]) => (
                <button key={k} onClick={() => setLayout(k)}
                  className={`px-3 py-1.5 rounded-md text-sm ${layout === k ? 'bg-white shadow text-gray-900' : 'text-gray-500'}`}>{label}</button>
              ))}
            </div>
            <span className="text-sm text-gray-500">
              {pendingCount ? `باقي ${pendingCount} صنف محتاج تأكيد` : sheet.ready ? 'جاهز للطباعة' : 'مفيش صنف مؤكد للطباعة'}
            </span>
            {canAct && (
              <button onClick={() => print.mutate()} disabled={!sheet.ready || print.isPending}
                className="ms-auto px-5 py-2 rounded-lg bg-primary text-white font-medium disabled:opacity-40"
                data-tour="usage-print-print">🖨️ طباعة (F9)</button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Settings tab ──────────────────────────────────────────────────────────────

const PRESET_LABELS = { amount: 'الكمية', frequency: 'عدد المرات', timing: 'التوقيت', phrase: 'جمل جاهزة' }

function SettingsTab({ canEdit }) {
  const qc = useQueryClient()
  const [noticeBar, toast] = useNotice()
  const q = useQuery({ queryKey: ['usage-print', 'settings'], queryFn: () => usagePrintApi.settings().then(r => r.data) })
  const [presets, setPresets] = useState(null)
  const [slip, setSlip] = useState(null)
  useEffect(() => {
    if (!q.data) return
    setPresets(Object.fromEntries(Object.entries(q.data.presets).map(([k, v]) => [k, v.join('\n')])))
    setSlip(q.data.slip)
  }, [q.data])
  const save = useMutation({
    mutationFn: () => usagePrintApi.saveSettings({
      presets: Object.fromEntries(Object.entries(presets).map(([k, v]) => [k, v.split('\n').map(s => s.trim()).filter(Boolean)])),
      slip,
    }).then(r => r.data),
    onSuccess: (d) => { qc.setQueryData(['usage-print', 'settings'], d); qc.invalidateQueries({ queryKey: ['usage-print', 'sheet'] }); toast.ok('تم الحفظ') },
    onError: (e) => toast.error(errText(e)),
  })
  if (q.isLoading || !presets || !slip) return <div className="py-12 text-center text-gray-400">جاري التحميل…</div>
  return (
    <div className="space-y-4" data-tour="usage-print-settings">
      {!canEdit && <div className="text-xs text-gray-500">عرض فقط — التعديل للمشرف والمدير.</div>}
      {noticeBar}
      <div className="grid md:grid-cols-2 gap-3">
        {Object.keys(PRESET_LABELS).map(k => (
          <label key={k} className="flex flex-col bg-white rounded-xl border p-3 text-sm text-gray-600">
            {PRESET_LABELS[k]} <span className="text-[11px] text-gray-400">سطر لكل اختيار</span>
            <textarea rows={6} disabled={!canEdit} value={presets[k] || ''}
              onChange={e => setPresets(p => ({ ...p, [k]: e.target.value }))}
              className="mt-1 border rounded-lg px-3 py-2 text-gray-900" />
          </label>
        ))}
      </div>
      <div className="bg-white rounded-xl border p-3 space-y-2">
        <div className="font-medium text-gray-800">أسفل الورقة <span className="text-xs text-gray-400">(الخانة الفارغة = لا يظهر)</span></div>
        {Object.entries(q.data.slip_labels).map(([key, label]) => (
          <label key={key} className="flex flex-col text-sm text-gray-600">{label}
            <input disabled={!canEdit} value={slip[key] || ''} onChange={e => setSlip(s => ({ ...s, [key]: e.target.value }))}
              className="mt-1 border rounded-lg px-3 py-2 text-gray-900" dir={key.endsWith('qr_url') ? 'ltr' : 'rtl'} />
          </label>
        ))}
      </div>
      {canEdit && (
        <button onClick={() => save.mutate()} disabled={save.isPending} data-tour="usage-print-settings-save"
          className="px-5 py-2 rounded-lg bg-primary text-white font-medium disabled:opacity-50">حفظ</button>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function UsagePrintPage() {
  const [tab, setTab] = useState('print')
  useHelpTab(tab)
  const user = useAuthStore(s => s.user)
  const perms = useQuery({ queryKey: ['usage-print', 'settings'], queryFn: () => usagePrintApi.settings().then(r => r.data), retry: false })

  if (user && !user.can_usage_print) {
    return (
      <div className="p-6 max-w-3xl mx-auto text-center" dir="rtl">
        <div className="text-4xl mb-2">🔒</div>
        <p className="text-gray-600">هذه الشاشة غير مفعّلة أو ليست ضمن صلاحياتك.</p>
      </div>
    )
  }
  const canEdit = !!perms.data?.perms?.can_edit
  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto" dir="rtl">
      <div className="mb-3">
        <h1 className="text-2xl font-bold text-gray-900">طريقة الاستخدام</h1>
        <p className="text-sm text-gray-500 mt-1">اطبع طريقة استخدام كل صنف في الفاتورة على ورق الإيصال. كل اقتراح لازم يتأكد قبل الطباعة.</p>
      </div>
      <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-4" data-tour="usage-print-tabs">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'print' ? <PrintTab /> : <SettingsTab canEdit={canEdit} />}
    </div>
  )
}
