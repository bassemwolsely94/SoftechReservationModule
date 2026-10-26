/** Contract (تعاقد) fast entry — patient autocomplete, «آخر روشتة» cards, per-visit highlight,
 *  approval-reuse warning, free-text suggestions. Display + interaction only: the backend owns the
 *  history/revalidation; nothing here blocks a send (a re-used approval number is only a warning). */
import { useEffect, useRef, useState } from 'react'
import { Badge, Icon } from '../design'
import useBranchNames from '../search/useBranchNames'
import useContractAssist, { useDebounced } from './useContractAssist'

const FREE_TEXT = ['deptname', 'comment', 'relativedegree', 'patientnationality']
const personcodeOf = (P) => P.customer?.personcode || P.customer?.cust_branch_code || ''
const fmtMoney = (n) => Number(n || 0).toLocaleString('en', { maximumFractionDigits: 2 })
const dateOf = (iso) => (iso || '').slice(0, 10)
const SOURCE = { pos: 'POS', insurance: 'تأمين' }
const FRESH_RING = 'ring-2 ring-amber-400 bg-amber-50'

/** One claim input. Adds to the plain input: patient / membership autocomplete, free-text value
 *  suggestions, the per-visit highlight and the approval-reuse warning. Used by the desktop tab and both
 *  mobile views, so the behaviour is identical everywhere. */
export function ClaimField({ P, k, type, className = 'inp' }) {
  const pc = personcodeOf(P)
  const A = useContractAssist({ personcode: pc, branchId: P.branch })
  const branchName = useBranchNames()
  const value = P.claim[k] || ''
  const [focus, setFocus] = useState(false)
  const [opts, setOpts] = useState([])
  const [warn, setWarn] = useState(null)
  const dq = useDebounced(value)
  const isPatient = k === 'patientname' || k === 'membershipno'
  const isFree = FREE_TEXT.includes(k)
  const fresh = (P.freshCols || []).includes(k)

  useEffect(() => {
    if (!pc || !focus || !(isPatient || isFree)) { setOpts([]); return }
    let alive = true
    if (isPatient) {
      A.suggestPatients(k === 'patientname' ? dq : '').then(rows => {
        if (!alive) return
        const f = k === 'membershipno'
          ? rows.filter(r => r.fields?.membershipno && String(r.fields.membershipno).includes(dq.trim()))
          : rows
        setOpts(f.slice(0, 8))
      }).catch(() => alive && setOpts([]))
    } else {
      A.fieldValues(k, dq).then(v => alive && setOpts(v)).catch(() => alive && setOpts([]))
    }
    return () => { alive = false }
  }, [pc, focus, dq, k, isPatient, isFree])   // eslint-disable-line react-hooks/exhaustive-deps

  const choose = (r) => {
    P.applyContractPatient(r.patientname, r.fields || {}, A.config.per_visit_columns || [])
    setOpts([])
  }
  const onBlur = () => {
    setTimeout(() => setFocus(false), 150)   // let a dropdown click land first
    if (k === A.config.approval_column && value.trim()) {
      A.checkApproval(value.trim()).then(r => setWarn(r.reused ? r.matches : null)).catch(() => setWarn(null))
    } else setWarn(null)
  }
  return (
    <div className="relative">
      <input type={type || 'text'} value={value} className={`${className} ${fresh ? FRESH_RING : ''}`}
             onFocus={() => setFocus(true)} onBlur={onBlur}
             onChange={e => { P.setClaimField(k, e.target.value); if (k === A.config.approval_column) setWarn(null) }} />
      {fresh && <span className="text-[10px] text-amber-700 font-medium">جديد لهذه الزيارة</span>}
      {warn && (
        <div className="text-[11px] text-amber-800 bg-amber-50 border border-amber-300 rounded px-1.5 py-1 mt-0.5 flex gap-1 items-start">
          <Icon name="alert" size={12} />
          <span>رقم الموافقة استُخدم من قبل في {warn.slice(0, 3).map(m =>
            `${dateOf(m.date)}${m.branch_id ? ' · ' + (branchName(m.branch_id) || '') : ''}${m.patientname ? ' · ' + m.patientname : ''}`).join(' ، ')}
            {warn.length > 3 ? ` (+${warn.length - 3})` : ''}</span>
        </div>
      )}
      {focus && isPatient && opts.length > 0 && (
        <div className="absolute z-30 inset-x-0 top-full mt-0.5 bg-white border border-gray-300 rounded shadow-lg max-h-56 overflow-auto">
          {opts.map((r, i) => (
            <button key={i} type="button" onMouseDown={e => e.preventDefault()} onClick={() => choose(r)}
                    className="w-full text-start px-2 py-1.5 text-xs hover:bg-blue-50 flex items-center justify-between gap-2 border-b last:border-0">
              <span className="font-medium">{r.patientname}{r.fields?.membershipno ? ` · ${r.fields.membershipno}` : ''}</span>
              <span className="text-gray-400 shrink-0">{dateOf(r.last_date)} · {SOURCE[r.source] || r.source}</span>
            </button>
          ))}
        </div>
      )}
      {focus && isFree && opts.length > 0 && (
        <div className="absolute z-30 inset-x-0 top-full mt-0.5 bg-white border border-gray-300 rounded shadow-lg max-h-40 overflow-auto">
          {opts.map(v => (
            <button key={v} type="button" onMouseDown={e => e.preventDefault()}
                    onClick={() => { P.setClaimField(k, v); setOpts([]) }}
                    className="w-full text-start px-2 py-1 text-xs hover:bg-blue-50">{v}</button>
          ))}
        </div>
      )}
    </div>
  )
}

/** «آخر روشتة» cards for the chosen patient + the skipped-lines note. Rendered above the claim fields. */
export default function ContractAssist({ P, mobile = false }) {
  const pc = personcodeOf(P)
  const A = useContractAssist({ personcode: pc, branchId: P.branch })
  const [cards, setCards] = useState(null)       // null = closed
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)         // { added, skipped:[] }
  const name = (P.claim.patientname || '').trim()
  const seq = useRef(0)
  useEffect(() => { setCards(null); setNote(null) }, [name, pc])
  if (!P.isClaim || !pc) return null

  const open = async () => {
    if (cards) { setCards(null); return }
    const my = ++seq.current
    setBusy(true)
    try { const r = await A.history(name); if (seq.current === my) setCards(r.slice(0, 5)) }
    catch { if (seq.current === my) setCards([]) }
    finally { setBusy(false) }
  }
  const apply = async (c) => {
    if (busy) return
    setBusy(true)
    try {
      const { skipped, needBatch } = await P.applyPrescriptionLines(c.revalidated)
      setNote({ added: (c.revalidated?.lines?.length || 0) - skipped.length, skipped, needBatch })
      setCards(null)
    } finally { setBusy(false) }
  }
  const WHY = { missing: 'صنف غير موجود', blocked: 'ممنوع البيع', out_of_stock: 'غير متوفر بالفرع' }
  const label = (l) => `${l.name || 'صنف غير معروف'} (${WHY[l.status] || l.status})`
  return (
    <div className="mb-3">
      <button type="button" disabled={!name || busy} onClick={open}
              title={name ? 'آخر روشتات هذا المريض' : 'اختر المريض أولاً'}
              className="inline-flex items-center gap-1.5 text-xs font-medium rounded border border-blue-300 text-blue-800 bg-blue-50 px-2.5 py-1.5 disabled:opacity-40">
        <Icon name="rx" size={14} /> آخر روشتة {busy && '…'}
      </button>
      {cards && (
        cards.length === 0
          ? <div className="text-xs text-gray-500 mt-2">لا توجد روشتات سابقة لهذا المريض.</div>
          : <div className={`mt-2 flex gap-2 ${mobile ? 'overflow-x-auto pb-1' : 'flex-wrap'}`}>
              {cards.map(c => {
                const s = c.revalidated?.summary || {}
                const bad = (s.out_of_stock || 0) + (s.blocked || 0) + (s.missing_item || 0)
                return (
                  <button key={`${c.source}-${c.ref}`} type="button" disabled={busy} onClick={() => apply(c)}
                          className="text-start border border-gray-300 rounded-lg px-2.5 py-1.5 bg-white hover:border-blue-500 disabled:opacity-50 shrink-0 min-w-[9.5rem]">
                    <div className="text-xs font-semibold">{dateOf(c.date)}</div>
                    <div className="text-[11px] text-gray-600">{s.total_lines ?? c.revalidated?.lines?.length ?? 0} أصناف · {fmtMoney(c.total)} ج</div>
                    <div className="mt-0.5 flex gap-1">
                      <Badge tone="neutral" size="xs">{SOURCE[c.source] || c.source}</Badge>
                      {bad > 0 && <Badge tone="warn" size="xs">{bad} لن تُضاف</Badge>}
                    </div>
                  </button>
                )
              })}
            </div>
      )}
      {note && (
        <div className="mt-2 text-xs rounded border border-gray-200 bg-gray-50 px-2 py-1.5">
          <span className="text-green-700">أُضيف {note.added} صنف من الروشتة — راجع الكميات.</span>
          {note.needBatch?.length > 0 && (
            <div className="text-amber-800 mt-0.5">يتطلب اختيار التشغيلة: {note.needBatch.join(' ، ')}</div>
          )}
          {note.skipped.length > 0 && (
            <div className="text-amber-800 mt-0.5">لم يُضف: {note.skipped.map(label).join(' ، ')}</div>
          )}
        </div>
      )}
    </div>
  )
}
