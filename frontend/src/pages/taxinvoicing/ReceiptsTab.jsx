/**
 * E-receipts for branch POS sales: per-branch summary and actions, the list with hold reasons, reading
 * a branch's day from SOFTECH (read only), and each branch's POS setup and the channel rules. Issuing
 * freezes receipts into the branch's chain. A real send comes only after a dry run, needs `finalize`
 * and the typed branch code, and is off while the server's switch is off.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import useBranchLabels from '../../hooks/useBranchLabels'
import {
  ActionMsg, Badge, Btn, Failed, Field, fmt, fmtDate, fmtInt, fmtTime, Grid, INPUT, LINE_STATUS_TONE, Loading, Notice,
  RECEIPT_STATUS_TONE, Section, useAction, useBranchOptions,
} from './ui'

const CONFIG_FIELDS = [
  ['seller_branch_code', 'كود فرع المصلحة'], ['device_serial', 'سيريال الجهاز'], ['pos_os_version', 'إصدار نظام الجهاز'],
  ['pos_model_framework', 'طراز الجهاز'], ['client_id', 'معرف العميل (Client ID)'], ['secret_env', 'اسم متغير السر'],
  ['preshared_key_env', 'اسم متغير المفتاح'], ['activity_code', 'كود النشاط'], ['governate', 'المحافظة'],
  ['region_city', 'المدينة'], ['street', 'الشارع'], ['building_number', 'رقم المبنى'], ['payment_method', 'طريقة الدفع'],
]
const CHANNEL_MODES = [['receipt', 'إيصال إلكتروني'], ['invoice', 'فاتورة على مطالبة'], ['undecided', 'لم يتحدد']]

// What the server answered about a real send: an uncertain batch stops the branch until it is asked.
const sentMessage = d => (d.status === 'uncertain'
  ? `نتيجة غير مؤكدة لـ ${fmtInt(d.count)} إيصال. لن يُرسل شيء من هذا الفرع قبل «استعلام من المصلحة».`
  : `أُرسلت دفعة من ${fmtInt(d.count)} إيصال. راجع حالاتها، واستعلم من المصلحة عن قرارها.`)

export function BranchActions({ branch, label, me }) {
  const act = useAction()
  const [dry, setDry] = useState(null)
  const [confirm, setConfirm] = useState('')
  return (
    <div className="space-y-2" data-tour="tax-invoicing-main-receipts-branch-actions">
      <div className="flex flex-wrap items-center gap-2">
        {me.can_approve && (
          <Btn disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.issueReceipts(branch), d => `صدر ${fmtInt(d.issued)} إيصال في سلسلة الفرع`)}>إصدار الجاهز</Btn>
        )}
        {me.can_finalize && (
          <>
            <Btn disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.previewReceipts(branch), null, setDry)}>معاينة الإرسال</Btn>
            <Btn disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.reconcileReceipts(branch), d => `تغير ${fmtInt(d.changed)} · بدون تغيير ${fmtInt(d.unchanged)}`)}>استعلام من المصلحة</Btn>
          </>
        )}
        <ActionMsg msg={act.msg} />
      </div>
      {dry && (
        <Notice tone="gray">
          معاينة فقط: {fmtInt(dry.count)} إيصال جاهز للدفعة التالية، ولم يُرسل شيء.
          {!dry.submit_enabled && ' الإرسال الفعلي للإيصالات مغلق.'}
          {dry.receipts?.length > 0 && (
            <ul className="mt-1 text-xs list-disc ms-5">
              {dry.receipts.map(r => <li key={r.id}>{r.receipt_number} · {fmt(r.total)} ج.م</li>)}
            </ul>
          )}
        </Notice>
      )}
      {dry && me.can_finalize && (
        <div className="flex flex-wrap items-end gap-2" data-tour="tax-invoicing-main-receipts-send">
          <Field label={`للإرسال الفعلي اكتب كود الفرع: ${label || branch}`}>
            <input dir="ltr" autoComplete="off" value={confirm} onChange={e => setConfirm(e.target.value)} className={`${INPUT} w-32`} />
          </Field>
          <Btn variant="danger" disabled={act.pending || !dry.submit_enabled || !dry.count || !confirm.trim()}
            onClick={() => act.run(() => taxInvoicingApi.submitReceipts(branch, confirm.trim()), sentMessage, () => { setConfirm(''); setDry(null) })}>
            إرسال الدفعة للمصلحة
          </Btn>
          <span className="text-[11px] text-gray-500">
            {!dry.submit_enabled ? 'معطل طالما الإرسال الفعلي مغلق.' : !dry.count ? 'لا توجد إيصالات صادرة للإرسال.' : 'ما يُرسل لا يُسحب.'}
          </span>
        </div>
      )}
    </div>
  )
}

function ReceiptDetail({ id }) {
  const { data: r, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'receipt', id],
    queryFn: () => taxInvoicingApi.receipt(id).then(x => x.data),
  })
  if (isLoading) return <Loading />
  if (error) return <Failed error={error} />
  return (
    <div className="space-y-2">
      {r.hold_reasons?.length > 0 && (
        <Notice tone="amber">
          <div className="font-bold text-xs mb-0.5">أسباب الحجز</div>
          <ul className="list-disc ms-5 text-xs">{r.hold_reasons.map((h, i) => <li key={i}>{h.itemcode ? `${h.itemcode}: ` : ''}{h.message}</li>)}</ul>
        </Notice>
      )}
      <div className="flex flex-wrap gap-x-5 text-xs text-gray-600">
        <span>الصافي: {fmt(r.net_amount)}</span>
        <span>الضريبة: {fmt(r.vat_amount)}</span>
        <span className="font-bold">الإجمالي: {fmt(r.total_amount)}</span>
        {r.uuid && <span>UUID: <span dir="ltr" className="font-mono break-all">{r.uuid}</span></span>}
        {r.eta_reason && <span className="text-red-700">رد المصلحة: {r.eta_reason}</span>}
      </div>
      <Grid getKey={l => `${l.itemcode}|${l.quantity}|${l.total}`} rows={r.lines} columns={[
        { key: 'itemcode', label: 'الكود' },
        { key: 'item_name', label: 'الصنف', render: l => l.item_name || '—' },
        { key: 'quantity', label: 'الكمية', type: 'number', render: l => fmt(l.quantity, 3) },
        { key: 'total', label: 'الإجمالي', type: 'number', render: l => fmt(l.total) },
        { key: 'source_vat_rate', label: 'ضريبة SOFTECH %', type: 'number', render: l => fmt(l.source_vat_rate) },
        { key: 'vat_rate', label: 'الضريبة المؤكدة %', type: 'number', render: l => fmt(l.vat_rate) },
        { key: 'status_label', label: 'الحالة', render: l => <Badge tone={LINE_STATUS_TONE[l.status]}>{l.status_label}</Badge> },
        { key: 'reason', label: 'السبب', render: l => l.reason || '—' },
      ]} />
    </div>
  )
}

function ReceiptsList({ initialStatus, statuses, bl }) {
  const [f, setF] = useState({ branch: '', status: initialStatus, channel: '', from: '', to: '' })
  const [open, setOpen] = useState(null)
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  const branches = useBranchOptions()
  const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v.trim()))
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'receipts', params],
    queryFn: () => taxInvoicingApi.receipts(params).then(r => ({ rows: r.data, total: Number(r.headers?.['x-total-count'] ?? r.data.length) })),
    placeholderData: prev => prev,
  })
  const columns = [
    { key: 'branch', label: 'الفرع', value: r => bl(r.branch), render: r => bl(r.branch), className: 'whitespace-nowrap' },
    { key: 'docnumber', label: 'المستند', render: r => `${r.doccode} / ${r.docnumber}`, className: 'whitespace-nowrap' },
    { key: 'docdate', label: 'التاريخ', type: 'date', render: r => fmtDate(r.docdate), className: 'whitespace-nowrap' },
    { key: 'sold_at', label: 'وقت البيع', type: 'date', render: r => fmtTime(r.sold_at), className: 'whitespace-nowrap' },
    { key: 'channel', label: 'القناة', render: r => r.channel || '—' },
    { key: 'source_value', label: 'قيمة المصدر', type: 'number', render: r => fmt(r.source_value), className: 'font-bold' },
    { key: 'status_label', label: 'الحالة', render: r => <Badge tone={RECEIPT_STATUS_TONE[r.status]}>{r.status_label}</Badge> },
    { key: 'hold', label: 'أسباب الحجز', value: r => r.hold_reasons?.length || 0, type: 'number', render: r => (r.hold_reasons?.length ? fmtInt(r.hold_reasons.length) : '—') },
  ]
  return (
    <Section title="الإيصالات" hint={data ? `معروض ${fmtInt(data.rows.length)} من ${fmtInt(data.total)} بهذه الفلاتر.` : ''} data-tour="tax-invoicing-main-receipts-list">
      <div className="flex flex-wrap items-end gap-2 mb-3">
        <Field label="الفرع">
          <select value={f.branch} onChange={e => set('branch', e.target.value)} className={INPUT}>
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.code} value={b.code}>{b.name || b.code}</option>)}
          </select>
        </Field>
        <Field label="الحالة">
          <select value={f.status} onChange={e => set('status', e.target.value)} className={INPUT}>
            <option value="">الكل</option>
            {statuses.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </Field>
        <Field label="القناة">
          <input value={f.channel} onChange={e => set('channel', e.target.value)} className={`${INPUT} w-24`} />
        </Field>
        <Field label="من"><input type="date" value={f.from} onChange={e => set('from', e.target.value)} className={INPUT} /></Field>
        <Field label="إلى"><input type="date" value={f.to} onChange={e => set('to', e.target.value)} className={INPUT} /></Field>
      </div>
      {isLoading ? <Loading /> : error ? <Failed error={error} /> : (
        <Grid columns={columns} rows={data.rows} empty="لا توجد إيصالات بهذه الفلاتر"
          onOpen={r => setOpen(o => (o === r.id ? null : r.id))} openKey={open} renderOpen={r => <ReceiptDetail id={r.id} />} />
      )}
    </Section>
  )
}

function ImportDay() {
  const act = useAction()
  const branches = useBranchOptions()
  const [branch, setBranch] = useState('')
  const [date, setDate] = useState('')
  return (
    <Section title="استيراد يوم من SOFTECH" hint="قراءة فقط من سيرفر الفرع. إعادة الاستيراد لا تكرر الإيصالات." data-tour="tax-invoicing-main-receipts-import">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="الفرع">
          <select value={branch} onChange={e => setBranch(e.target.value)} className={INPUT}>
            <option value="">اختر فرعاً…</option>
            {branches.map(b => <option key={b.code} value={b.code}>{b.name || b.code}</option>)}
          </select>
        </Field>
        <Field label="اليوم"><input type="date" value={date} onChange={e => setDate(e.target.value)} className={INPUT} /></Field>
        <Btn variant="primary" disabled={act.pending || !branch || !date}
          onClick={() => act.run(() => taxInvoicingApi.importReceipts({ branch, date }), d => `جديد ${fmtInt(d.created)} · محدث ${fmtInt(d.updated)} · مستندات ${fmtInt(d.documents)}`)}>
          {act.pending ? 'جارٍ القراءة من SOFTECH…' : 'استيراد اليوم'}
        </Btn>
        <ActionMsg msg={act.msg} />
      </div>
    </Section>
  )
}

function ConfigEditor({ branch, row, me, onDone }) {
  const act = useAction()
  const can = me.can_finalize
  const [f, setF] = useState(() => ({
    is_enabled: !!row?.is_enabled,
    ...Object.fromEntries(CONFIG_FIELDS.map(([k]) => [k, row?.[k] || ''])),
  }))
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-1.5 text-xs text-gray-700">
        <input type="checkbox" disabled={!can} checked={f.is_enabled} onChange={e => set('is_enabled', e.target.checked)} /> الفرع مفعل للإيصال الإلكتروني
      </label>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {CONFIG_FIELDS.map(([k, label]) => (
          <Field key={k} label={label}>
            <input value={f[k]} disabled={!can} onChange={e => set(k, e.target.value)} className={INPUT} />
          </Field>
        ))}
      </div>
      <p className="text-[11px] text-gray-500">الأسرار نفسها في إعدادات السيرفر؛ هنا يُكتب اسم المتغير فقط.</p>
      {can && (
        <Btn variant="primary" disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.saveReceiptConfig({ branch, ...f }), 'تم الحفظ', onDone)}>حفظ إعداد الفرع</Btn>
      )}
      <ActionMsg msg={act.msg} />
    </div>
  )
}

/**
 * Where this device's receipt chain starts, decided once before its first receipt, from ETA's own answer:
 * a fresh device starts empty; a device another program (Invoicer) used continues after its last receipt.
 */
export function ChainStart({ branch, row, me }) {
  const act = useAction()
  const [found, setFound] = useState(null)
  const [stopped, setStopped] = useState(false)
  const [confirm, setConfirm] = useState('')
  const [reason, setReason] = useState('')
  const short = v => (v ? `${v.slice(0, 12)}…` : '—')
  if (row.chain_start) {
    const latest = row.chain_start_detail?.latest
    return (
      <div className="space-y-2 text-xs" data-tour="tax-invoicing-main-receipts-chain">
        <div className="flex flex-wrap gap-2 items-center">
          <Badge tone="bg-emerald-50 text-emerald-700 border-emerald-200">{row.chain_start_label}</Badge>
          <span className="text-gray-500">{fmtTime(row.chain_start_at)} · {row.chain_start_by}</span>
          {latest && <span className="text-gray-500">بعد الإيصال {latest.receipt_number || '—'} (<span dir="ltr" className="font-mono">{short(latest.uuid)}</span>)</span>}
        </div>
        {me.can_finalize && !row.has_chain_receipts && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label="سبب التراجع"><input className={`${INPUT} w-56`} value={reason} onChange={e => setReason(e.target.value)} /></Field>
            <Btn variant="danger" disabled={act.pending || !reason.trim()}
              onClick={() => act.run(() => taxInvoicingApi.undoChainStart(branch, reason), 'تم التراجع عن بداية السلسلة')}>تراجع</Btn>
          </div>
        )}
        <ActionMsg msg={act.msg} />
      </div>
    )
  }
  if (!me.can_finalize) return <Notice tone="gray">لم تتحدد بداية سلسلة هذا الجهاز بعد؛ يحددها من يملك الاعتماد النهائي.</Notice>
  const latest = found?.latest
  return (
    <div className="space-y-2 text-xs" data-tour="tax-invoicing-main-receipts-chain">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-bold text-gray-700">بداية سلسلة الجهاز:</span>
        <Btn disabled={act.pending || !row.device_serial} data-tour="tax-invoicing-main-receipts-chain-lookup"
          onClick={() => act.run(() => taxInvoicingApi.chainLookup(branch), null, d => { setFound(d); setStopped(false); setConfirm('') })}>
          ابحث في المصلحة عن إيصالات هذا الجهاز
        </Btn>
      </div>
      {found && !latest && (
        <Notice tone="green">المصلحة لا تعرض أي إيصال من الجهاز {found.device_serial} خلال آخر {fmtInt(found.looked_back_days)} يوم: يبدأ كجهاز جديد.</Notice>
      )}
      {latest && (
        <Notice tone="amber">
          الجهاز {found.device_serial} استُخدم من قبل ({latest.submitter || 'برنامج آخر'}). أحدث إيصال لدى المصلحة:
          رقم {latest.receipt_number || '—'} بتاريخ {fmtTime(latest.issued)}، حالته {latest.status || '—'}،
          ومعرّفه <span dir="ltr" className="font-mono">{short(latest.uuid)}</span>. أول إيصال لنا سيأتي بعده مباشرة.
        </Notice>
      )}
      {found && (
        <div className="flex flex-wrap items-end gap-2">
          {latest && (
            <label className="flex items-center gap-1.5 text-gray-700">
              <input type="checkbox" checked={stopped} onChange={e => setStopped(e.target.checked)} />
              تأكدت أن البرنامج السابق توقف عن الإصدار على هذا الجهاز
            </label>
          )}
          <Field label={`اكتب كود الفرع (${branch}) للتأكيد`}>
            <input className={`${INPUT} w-24`} value={confirm} onChange={e => setConfirm(e.target.value)} />
          </Field>
          <Btn variant="primary" disabled={act.pending || confirm !== branch || (latest && !stopped)}
            data-tour="tax-invoicing-main-receipts-chain-start"
            onClick={() => act.run(() => taxInvoicingApi.startChain(branch, latest
              ? { mode: 'handover', confirm, other_program_stopped: stopped, expected_uuid: latest.uuid }
              : { mode: 'fresh', confirm }), 'تحددت بداية السلسلة')}>
            {latest ? 'استلام السلسلة بعد هذا الإيصال' : 'بدء سلسلة جديدة'}
          </Btn>
        </div>
      )}
      <ActionMsg msg={act.msg} />
    </div>
  )
}

/**
 * A test-only mapping: this branch's sales go to ETA's test system through a borrowed test device. The server
 * refuses it anywhere else; ending it puts the test receipts back to ready for the real system.
 */
/** From when this branch's sales are sent from here. Earlier sales stay held ("before the start"). */
export function SendFrom({ branch, row, me }) {
  const act = useAction()
  const [when, setWhen] = useState(row.send_from ? String(row.send_from).slice(0, 16) : '')
  const [reason, setReason] = useState('')
  return (
    <div className="flex flex-wrap items-end gap-2" data-tour="tax-invoicing-main-receipts-send-from">
      <Field label="بداية الإرسال" hint={row.send_from ? `الحالية: ${fmtTime(row.send_from)}` : 'لم تتحدد — المبيعات قبلها لا تُرسل من هنا'}>
        <input type="datetime-local" className={INPUT} value={when} onChange={e => setWhen(e.target.value)} aria-label="بداية الإرسال" disabled={!me.can_finalize} />
      </Field>
      {me.can_finalize && (
        <>
          <Field label="السبب">
            <input className={`${INPUT} w-48`} value={reason} onChange={e => setReason(e.target.value)} aria-label="سبب بداية الإرسال" />
          </Field>
          <Btn disabled={!when || act.pending}
            onClick={() => act.run(() => taxInvoicingApi.setSendFrom(branch, { send_from: new Date(when).toISOString(), reason }),
              d => `تحددت بداية الإرسال · أُعيد فحص ${fmtInt(d.rechecked)} إيصال`)}>
            حفظ بداية الإرسال
          </Btn>
        </>
      )}
      <ActionMsg msg={act.msg} />
    </div>
  )
}

export function TestMapping({ branch, row, me }) {
  const act = useAction()
  const [reason, setReason] = useState('')
  if (!me.can_finalize && !row.test_env) return null
  if (row.test_env) {
    return (
      <div className="space-y-2" data-tour="tax-invoicing-main-receipts-test-mapping">
        <Notice tone="warn">إعداد تجريبي فقط ({row.test_env}): لا يُرسل لمنظومة غيرها، وإيصالاته لا تُحسب للمنظومة الفعلية.</Notice>
        {me.can_finalize && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label="سبب إنهاء الإعداد التجريبي">
              <input className={`${INPUT} w-64`} value={reason} onChange={e => setReason(e.target.value)} aria-label="سبب إنهاء الإعداد التجريبي" />
            </Field>
            <Btn disabled={!reason.trim() || act.pending}
              onClick={() => act.run(() => taxInvoicingApi.endTestMapping(branch, reason), 'انتهى الإعداد التجريبي وعادت إيصالاته جاهزة')}>
              إنهاء الإعداد التجريبي
            </Btn>
          </div>
        )}
        <ActionMsg msg={act.msg} />
      </div>
    )
  }
  if (row.has_chain_receipts) return null
  return (
    <div className="flex flex-wrap items-center gap-2" data-tour="tax-invoicing-main-receipts-test-mapping">
      <span className="text-xs text-gray-500">لتجربة مبيعات هذا الفرع على جهاز تجريبي في المنظومة التجريبية فقط.</span>
      <Btn disabled={act.pending}
        onClick={() => act.run(() => taxInvoicingApi.saveReceiptConfig({ branch, test_only: true }), 'أصبح الإعداد تجريبياً فقط')}>
        جعله إعداداً تجريبياً فقط
      </Btn>
      <ActionMsg msg={act.msg} />
    </div>
  )
}

function Configs({ me, bl }) {
  const branches = useBranchOptions()
  const [open, setOpen] = useState(null)
  const [adding, setAdding] = useState('')
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'receipt-configs'],
    queryFn: () => taxInvoicingApi.receiptConfigs().then(r => r.data),
  })
  if (isLoading) return <Loading />
  if (error) return <Failed error={error} />
  const known = new Set(data.map(c => c.branch))
  return (
    <Section title="إعداد الفروع" hint="جهاز كل فرع المسجل لدى المصلحة." data-tour="tax-invoicing-main-receipts-configs"
      actions={me.can_finalize && (
        <select value={adding} onChange={e => setAdding(e.target.value)} className={INPUT} aria-label="إضافة فرع">
          <option value="">＋ إضافة فرع…</option>
          {branches.filter(b => !known.has(b.code)).map(b => <option key={b.code} value={b.code}>{b.name || b.code}</option>)}
        </select>
      )}>
      {adding && (
        <div className="mb-3 p-3 rounded-lg bg-gray-50 border border-gray-100">
          <div className="font-bold text-sm mb-2">{bl(adding)}</div>
          <ConfigEditor key={adding} branch={adding} me={me} onDone={() => setAdding('')} />
        </div>
      )}
      <Grid getKey={c => c.branch} rows={data} empty="لا توجد فروع مسجلة بعد"
        onOpen={c => setOpen(o => (o === c.branch ? null : c.branch))} openKey={open}
        renderOpen={c => (
          <div className="space-y-3">
            <ConfigEditor key={c.branch} branch={c.branch} row={c} me={me} onDone={() => setOpen(null)} />
            <div className="border-t border-gray-100 pt-3"><SendFrom branch={c.branch} row={c} me={me} /></div>
            <div className="border-t border-gray-100 pt-3"><TestMapping branch={c.branch} row={c} me={me} /></div>
            <div className="border-t border-gray-100 pt-3"><ChainStart branch={c.branch} row={c} me={me} /></div>
          </div>
        )}
        columns={[
          { key: 'branch', label: 'الفرع', value: c => bl(c.branch), render: c => bl(c.branch) },
          { key: 'is_enabled', label: 'مفعل', render: c => (c.is_enabled ? '✔' : '—') },
          { key: 'seller_branch_code', label: 'كود المصلحة', render: c => c.seller_branch_code || '—' },
          { key: 'device_serial', label: 'سيريال الجهاز', render: c => (
            <span>{c.device_serial || '—'}{c.test_env && <> <Badge>تجريبي</Badge></>}</span>) },
          { key: 'send_from', label: 'بداية الإرسال', value: c => c.send_from || '', render: c => (c.send_from ? fmtTime(c.send_from) : 'لم تتحدد') },
          { key: 'chain_start', label: 'بداية السلسلة', value: c => c.chain_start_label, render: c => c.chain_start_label || 'لم تتحدد' },
        ]} />
    </Section>
  )
}

function ChannelEditor({ row, code = '', onDone }) {
  const act = useAction()
  const [f, setF] = useState({ ptclassifcode: row?.ptclassifcode || code, mode: row?.mode || 'undecided', label: row?.label || '', note: row?.note || '' })
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  return (
    <div className="flex flex-wrap items-end gap-2">
      {!row && (
        <Field label="كود القناة"><input dir="ltr" value={f.ptclassifcode} readOnly={!!code} onChange={e => set('ptclassifcode', e.target.value)} className={`${INPUT} w-24`} /></Field>
      )}
      <Field label="القرار">
        <select value={f.mode} onChange={e => set('mode', e.target.value)} className={INPUT}>
          {CHANNEL_MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </Field>
      <Field label="الاسم"><input value={f.label} onChange={e => set('label', e.target.value)} className={INPUT} /></Field>
      <Field label="ملاحظة" className="grow min-w-[200px]"><input value={f.note} onChange={e => set('note', e.target.value)} className={INPUT} /></Field>
      <Btn variant="primary" disabled={act.pending || !f.ptclassifcode.trim()}
        onClick={() => act.run(() => taxInvoicingApi.saveChannelRule(f), d => `تم الحفظ · أُعيد تقييم ${fmtInt(d.reevaluated)} إيصال`, onDone)}>حفظ</Btn>
      <ActionMsg msg={act.msg} />
    </div>
  )
}

function Channels({ me }) {
  const [open, setOpen] = useState(null)
  const [openSeen, setOpenSeen] = useState(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'channels'],
    queryFn: () => taxInvoicingApi.channelRules().then(r => r.data),
  })
  const seen = useQuery({
    queryKey: ['tax-invoicing', 'channels-seen'],
    queryFn: () => taxInvoicingApi.channelsSeen().then(r => r.data),
  })
  if (isLoading) return <Loading />
  if (error) return <Failed error={error} />
  // Channels on imported sales with no rule yet: their receipts are held until someone decides.
  const known = new Set(data.map(r => r.ptclassifcode))
  const undecided = (seen.data || []).filter(s => s.channel && !known.has(s.channel))
  return (
    <Section title="قواعد القنوات" hint="قناة بلا قرار تُحجز إيصالاتها ولا تُحذف. افتح القناة واحفظ لتأكيد قرارها." data-tour="tax-invoicing-main-receipts-channels">
      {undecided.length > 0 && (
        <div className="mb-3" data-tour="tax-invoicing-main-receipts-channels-seen">
          <div className="text-sm font-bold text-gray-800 mb-1">قنوات في المبيعات بلا قاعدة</div>
          <Grid getKey={s => s.channel} rows={undecided} defaultSort={{ key: 'documents', dir: 'desc', type: 'number' }}
            onOpen={me.can_approve ? s => setOpenSeen(o => (o === s.channel ? null : s.channel)) : undefined} openKey={openSeen}
            renderOpen={s => <ChannelEditor key={s.channel} code={s.channel} onDone={() => setOpenSeen(null)} />}
            columns={[
              { key: 'channel', label: 'القناة' },
              { key: 'documents', label: 'إيصالات', type: 'number', render: s => fmtInt(s.documents) },
              { key: 'value', label: 'القيمة', type: 'number', render: s => fmt(s.value) },
            ]} />
        </div>
      )}
      {me.can_approve && <div className="mb-3"><ChannelEditor /></div>}
      <Grid getKey={r => r.ptclassifcode} rows={data} empty="لا توجد قواعد بعد"
        onOpen={me.can_approve ? r => setOpen(o => (o === r.ptclassifcode ? null : r.ptclassifcode)) : undefined} openKey={open}
        renderOpen={r => <ChannelEditor key={r.ptclassifcode} row={r} onDone={() => setOpen(null)} />}
        columns={[
          { key: 'ptclassifcode', label: 'القناة' },
          { key: 'label', label: 'الاسم', render: r => r.label || '—' },
          { key: 'mode_label', label: 'القرار' },
          { key: 'note', label: 'ملاحظة', render: r => r.note || '—' },
          { key: 'confirmed_by', label: 'أكده', render: r => (r.confirmed_at
            ? <>{r.confirmed_by || '—'} <span className="text-[11px] text-gray-400">{fmtTime(r.confirmed_at)}</span></>
            : <Badge tone={RECEIPT_STATUS_TONE.held}>بانتظار تأكيد المحاسب</Badge>) },
        ]} />
    </Section>
  )
}

export default function ReceiptsTab({ me, initialStatus = '' }) {
  const bl = useBranchLabels()
  const [open, setOpen] = useState(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'receipts-summary'],
    queryFn: () => taxInvoicingApi.receiptsSummary().then(r => r.data),
  })
  if (isLoading) return <Loading />
  if (error) return <Failed error={error} />
  // One column per status, as the server lists them.
  const columns = [
    { key: 'branch', label: 'الفرع', value: r => bl(r.branch), render: r => bl(r.branch), className: 'font-medium whitespace-nowrap' },
    ...data.statuses.map(s => ({
      key: `s_${s.key}`, label: s.label, type: 'number', value: r => r.by_status[s.key] || 0,
      render: r => (r.by_status[s.key] ? fmtInt(r.by_status[s.key]) : <span className="text-gray-300">—</span>),
    })),
    { key: 'total', label: 'الإجمالي', type: 'number', render: r => fmtInt(r.total), className: 'font-bold' },
    { key: 'source_value', label: 'القيمة', type: 'number', render: r => fmt(r.source_value) },
  ]
  return (
    <div className="space-y-3">
      <Section title="ملخص الفروع" hint="اضغط الفرع لإصدار الجاهز أو معاينة الإرسال أو الاستعلام." data-tour="tax-invoicing-main-receipts-summary">
        <Grid columns={columns} rows={data.branches} getKey={r => r.branch} empty="لم تُستورد إيصالات بعد"
          onOpen={r => setOpen(o => (o === r.branch ? null : r.branch))} openKey={open}
          renderOpen={r => <BranchActions branch={r.branch} label={bl(r.branch)} me={me} />} />
      </Section>
      {me.can_create && <ImportDay />}
      <ReceiptsList initialStatus={initialStatus} statuses={data.statuses} bl={bl} />
      <Configs me={me} bl={bl} />
      <Channels me={me} />
    </div>
  )
}
