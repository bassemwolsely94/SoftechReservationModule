/**
 * GiftCouponsTab.jsx — «كوبونات الهدايا» (paper gift coupons, SOFTECH supplier 1268)
 *
 * Read-only views over the coupon mirror + batch stocking. The backend owns every rule
 * (apps/vouchers/coupon_views.py): who may view / manage, the SOFTECH writer gate, the
 * per-batch lock and the audit log. This screen only displays and asks.
 *
 *   • serial search   — full history of one coupon (issue → transfer → use)
 *   • العملاء          — customers who used more coupons than were issued to them
 *   • بدون سريال       — sale lines that used a coupon without a valid serial
 *   • الدفعات          — generate a batch, print sheet, rehearse, stock in SOFTECH, verify
 */
import { Fragment, useCallback, useEffect, useState } from 'react'
import { couponsApi } from '../../api/client'

const STAGE_LABEL = {
  stocked: 'في المخزن الرئيسي', issued: 'صُرف لعميل', at_branch: 'في فرع',
  redeemed: 'استُخدم', none: 'بدون حركة',
}
const KIND_TONE = {
  issue: 'text-sky-700', issue_return: 'text-sky-500', transfer_out: 'text-gray-600',
  transfer_in: 'text-gray-600', transfer_cancel: 'text-gray-400', redeem: 'text-emerald-700',
  redeem_return: 'text-amber-600',
}
const BATCH_TONE = {
  generated: 'bg-amber-50 text-amber-700', stocked: 'bg-emerald-50 text-emerald-700', void: 'bg-gray-100 text-gray-500',
}

const errMsg = (e, fallback = 'حدث خطأ') => e?.response?.data?.detail || e?.message || fallback
const n = v => (v ?? 0).toLocaleString('en-US', { maximumFractionDigits: 2 })

function Card({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 min-w-[9rem]">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-bold ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

function Btn({ children, variant = 'ghost', className = '', ...props }) {
  const v = {
    primary: 'bg-brand-600 text-white hover:bg-brand-700',
    danger:  'bg-red-600 text-white hover:bg-red-700',
    ghost:   'bg-white border border-gray-300 text-gray-700 hover:bg-gray-50',
  }[variant]
  return (
    <button {...props}
      className={`px-3 py-1.5 text-sm rounded-lg font-medium disabled:opacity-40 ${v} ${className}`}>
      {children}
    </button>
  )
}

function ErrorLine({ msg }) {
  return msg ? <div className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2 my-2">{msg}</div> : null
}

function EventsTable({ events, showSerial = false }) {
  if (!events?.length) return <div className="text-sm text-gray-400 py-3">لا توجد حركات.</div>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm text-right">
        <thead className="text-xs text-gray-500 border-b">
          <tr>
            <th className="py-2 px-2">التاريخ</th>
            {showSerial && <th className="px-2">السريال</th>}
            <th className="px-2">الحركة</th>
            <th className="px-2">المستند</th>
            <th className="px-2">الكمية</th>
            <th className="px-2">العميل</th>
            <th className="px-2">إلى فرع</th>
            <th className="px-2">مستخدم SOFTECH</th>
          </tr>
        </thead>
        <tbody>
          {events.map(e => (
            <tr key={e.id} className="border-b border-gray-50">
              <td className="py-1.5 px-2 whitespace-nowrap">{e.docdate}</td>
              {showSerial && <td className="px-2 font-mono" dir="ltr">{e.serial || '—'}</td>}
              <td className={`px-2 ${KIND_TONE[e.kind] || 'text-gray-500'}`}>{e.kind_label}</td>
              <td className="px-2 font-mono whitespace-nowrap" dir="ltr">{e.branchcode}/{e.doccode}/{e.docnumber}</td>
              <td className="px-2">{n(e.qty)}</td>
              <td className="px-2 font-mono" dir="ltr">{e.customer_pic || '—'}</td>
              <td className="px-2">{e.party_code || ''}</td>
              <td className="px-2">{e.usercode}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Serial search ────────────────────────────────────────────────────────────
function SerialSearch() {
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const search = async () => {
    const v = q.trim()
    if (!v) return
    setLoading(true); setError(null)
    try { setRes((await couponsApi.serial(v)).data) }
    catch (e) { setError(errMsg(e)); setRes(null) }
    finally { setLoading(false) }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4">
      <div className="flex gap-2 items-center">
        <input value={q} onChange={e => setQ(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && search()} dir="ltr"
          placeholder="27301-ABC123 أو 27301"
          className="flex-1 border border-gray-300 rounded-lg px-3 py-2 font-mono focus:outline-none focus:border-brand-500" />
        <Btn variant="primary" onClick={search} disabled={loading}>{loading ? '...' : 'بحث'}</Btn>
        {res && <Btn onClick={() => { setRes(null); setQ('') }}>مسح</Btn>}
      </div>
      <ErrorLine msg={error} />
      {res && !res.serials.length && !res.unlinked_events.length && (
        <div className="text-sm text-gray-500 mt-3">لا يوجد كوبون بهذا الرقم.</div>
      )}
      {res?.serials.map(s => (
        <div key={s.id} className="mt-4 border-t pt-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="font-mono font-bold text-base" dir="ltr">{s.serial}</span>
            <span className="px-2 py-0.5 rounded bg-gray-100">{s.stage_label || '—'}</span>
            <span className="text-gray-500">{s.status_label}</span>
            {s.expiry && <span className="text-gray-500">الصلاحية (مفتاح المخزون): {s.expiry}</span>}
            {s.points_docnumber && <span className="text-gray-500">شراء: {s.points_docnumber} / {s.served_docnumber}</span>}
            {s.issued_pic && <span>صُرف إلى <b className="font-mono">{s.issued_pic}</b> ({s.issued_at})</span>}
            {s.redeemed_at && <span>استُخدم في فرع {s.redeemed_branch} ({s.redeemed_at}) — عميل <b className="font-mono">{s.redeemed_pic || '—'}</b></span>}
          </div>
          {s.anomalies.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {s.anomalies.map(a => (
                <span key={a.code} className="text-xs bg-red-50 text-red-700 rounded px-2 py-0.5">{a.label}</span>
              ))}
            </div>
          )}
          {s.conflict_note && <div className="text-xs text-amber-700 mt-1">{s.conflict_note}</div>}
          <div className="mt-2"><EventsTable events={s.events} /></div>
        </div>
      ))}
      {res?.unlinked_events.length > 0 && (
        <div className="mt-4 border-t pt-3">
          <div className="text-sm font-medium text-red-700 mb-1">
            حركات مسجّلة بهذا النص كسريال وهو ليس سريال كوبون ({res.unlinked_events.length})
          </div>
          <EventsTable events={res.unlinked_events} />
        </div>
      )}
    </div>
  )
}

// ── POS guard rehearsal — the exact check /pos runs on push (works while the guard is off) ──
function GuardTest() {
  const [f, setF] = useState({ serial: '', branch: '', pic: '' })
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const set = k => e => setF(v => ({ ...v, [k]: e.target.value.toUpperCase() }))

  const run = async () => {
    if (!f.serial.trim()) return
    setLoading(true); setError(null); setRes(null)
    try {
      setRes((await couponsApi.check({ serial: f.serial.trim(), branch: f.branch.trim(), pic: f.pic.trim() })).data)
    } catch (e) { setError(errMsg(e)) } finally { setLoading(false) }
  }
  const input = 'border border-gray-300 rounded-lg px-3 py-2 font-mono focus:outline-none focus:border-brand-500'

  return (
    <details className="bg-white rounded-2xl border border-gray-200 p-4">
      <summary className="cursor-pointer text-sm font-medium text-gray-700">
        اختبار فحص الكوبون في POS — نفس القواعد التي ستطبق عند التفعيل
      </summary>
      <div className="flex flex-wrap gap-2 items-center mt-3" onKeyDown={e => e.key === 'Enter' && run()}>
        <input value={f.serial} onChange={set('serial')} dir="ltr" placeholder="السريال 27301-ABC123" className={`${input} flex-1 min-w-[12rem]`} />
        <input value={f.branch} onChange={set('branch')} dir="ltr" placeholder="كود الفرع 130" className={`${input} w-32`} />
        <input value={f.pic} onChange={set('pic')} dir="ltr" placeholder="كود العميل PIC" className={`${input} w-40`} />
        <Btn variant="primary" onClick={run} disabled={loading}>{loading ? '...' : 'فحص'}</Btn>
      </div>
      <div className="text-xs text-gray-400 mt-1">
        اترك الفرع فارغًا لتجاهل شرط «موجود في مخزون الفرع»، واترك العميل فارغًا لترى لمن صُرف الكوبون.
      </div>
      <ErrorLine msg={error} />
      {res && (
        <div className={`mt-3 rounded-lg p-3 text-sm ${res.ok ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}>
          <div className="font-bold">{res.ok ? `✓ سيُقبل الكوبون ${res.serial}` : `✗ سيُرفض الكوبون ${res.serial || ''}`}</div>
          {res.errors.map((m, i) => <div key={i}>• {m}</div>)}
          {res.info && Object.keys(res.info).length > 0 && (
            <div className="text-xs text-gray-600 mt-2 flex flex-wrap gap-x-4">
              <span>مُدخل: {n(res.info.stocked)}</span>
              <span>صُرف: {n(res.info.issued)}{res.info.issued_to ? ` إلى ${res.info.issued_to}` : ''}</span>
              <span>استُخدم: {n(res.info.redeemed)}</span>
              {res.info.branch_qty !== null && <span>رصيد الفرع: {n(res.info.branch_qty)}</span>}
              {res.info.expiry && <span>الصلاحية: {res.info.expiry}</span>}
              {res.info.held_by_orders?.length > 0 && <span>في أوامر مفتوحة: #{res.info.held_by_orders.join(', #')}</span>}
            </div>
          )}
        </div>
      )}
    </details>
  )
}

// ── Customers over their issued coupons ──────────────────────────────────────
function CustomersView() {
  const [data, setData] = useState(null)
  const [all, setAll] = useState(false)
  const [open, setOpen] = useState(null)       // { pic, data }
  const [error, setError] = useState(null)

  useEffect(() => {
    setData(null); setError(null)
    couponsApi.customers(all ? { all: 1 } : {}).then(r => setData(r.data)).catch(e => setError(errMsg(e)))
  }, [all])

  const toggle = async pic => {
    if (open?.pic === pic) { setOpen(null); return }
    setOpen({ pic, data: null })
    try { setOpen({ pic, data: (await couponsApi.customers({ pic })).data }) }
    catch (e) { setOpen(null); setError(errMsg(e)) }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2 text-sm">
        <div className="text-gray-600">
          عملاء استخدموا كوبونات أكثر مما صُرف لهم (الاستخدام منذ {data?.since || '…'}).
          {data && <> نشطون آخر 12 شهر: <b>{data.active_over}</b> عميل، <b>{n(data.active_excess)}</b> كوبون زيادة.</>}
        </div>
        <label className="flex items-center gap-1 text-gray-600">
          <input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} /> كل الفترات
        </label>
      </div>
      <ErrorLine msg={error} />
      {!data && !error && <div className="text-sm text-gray-400">جارٍ التحميل…</div>}
      {data && (
        <table className="w-full text-sm text-right bg-white rounded-xl border border-gray-200">
          <thead className="text-xs text-gray-500 border-b">
            <tr><th className="py-2 px-3">كود العميل</th><th>الاسم</th><th>صُرف له</th><th>استخدم</th><th>زيادة</th><th>آخر استخدام</th></tr>
          </thead>
          <tbody>
            {data.rows.map(r => (
              <Fragment key={r.pic}>
                <tr onClick={() => toggle(r.pic)}
                  className={`border-b border-gray-50 cursor-pointer hover:bg-gray-50 ${open?.pic === r.pic ? 'bg-gray-50' : ''}`}>
                  <td className="py-1.5 px-3 font-mono" dir="ltr">{r.pic}</td>
                  <td>{r.name}</td>
                  <td>{n(r.issued)}</td>
                  <td>{n(r.redeemed)}</td>
                  <td className="font-bold text-red-700">{n(r.excess)}</td>
                  <td>{r.last}</td>
                </tr>
                {open?.pic === r.pic && (
                  <tr><td colSpan={6} className="p-3 bg-gray-50">
                    {open.data ? <EventsTable events={open.data.events} showSerial /> : <span className="text-gray-400">…</span>}
                  </td></tr>
                )}
              </Fragment>
            ))}
            {!data.rows.length && <tr><td colSpan={6} className="py-4 text-center text-gray-400">لا يوجد</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Redemptions without a valid serial ───────────────────────────────────────
function NoSerialView() {
  const [branch, setBranch] = useState('')
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setData(null); setError(null)
    couponsApi.noSerial({ branch, days }).then(r => setData(r.data)).catch(e => setError(errMsg(e)))
  }, [branch, days])

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-3 text-sm">
        <span className="text-gray-600">سطور بيع استُخدم فيها كوبون بدون سريال صحيح —</span>
        <select value={days} onChange={e => setDays(Number(e.target.value))}
          className="border border-gray-300 rounded-lg px-2 py-1">
          {[7, 30, 90, 365].map(d => <option key={d} value={d}>آخر {d} يوم</option>)}
        </select>
        <select value={branch} onChange={e => setBranch(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1">
          <option value="">كل الفروع</option>
          {(data?.by_branch || []).map(b => <option key={b.branch} value={b.branch}>فرع {b.branch}</option>)}
          {branch && !(data?.by_branch || []).some(b => b.branch === branch) && <option value={branch}>فرع {branch}</option>}
        </select>
      </div>
      <ErrorLine msg={error} />
      {data && (
        <>
          <div className="flex flex-wrap gap-2 mb-3">
            {data.by_user.map(u => (
              <span key={`${u.branch}-${u.usercode}`} className="text-xs bg-white border border-gray-200 rounded-lg px-2 py-1">
                فرع {u.branch} · مستخدم {u.usercode || '؟'}: <b>{n(u.qty)}</b> كوبون / {u.lines} سطر
              </span>
            ))}
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-2">
            <EventsTable events={data.rows} showSerial />
          </div>
        </>
      )}
    </div>
  )
}

// ── Batches: generate → print → rehearse → stock → verify ────────────────────
function ProbeResult({ res }) {
  if (!res) return null
  return (
    <div className={`text-xs rounded-lg p-2 mt-2 ${res.clean ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-800'}`}>
      {res.clean ? 'التجربة سليمة: المستندان طابقا المستندات المرجعية وتم التراجع عنهما بالكامل.' : 'التجربة بها اختلافات:'}
      {Object.entries(res.legs).map(([leg, r]) => (
        <div key={leg} className="mt-1">
          <b>{leg === 'points' ? 'صنف النقاط' : 'صنف الاستحقاق'}</b>:
          {' '}سطور {r.lines_found}/{r.lines_expected} · تراجع {r.rolled_back ? '✓' : '✗'} · ترتيب السريالات {r.serials_ok ? '✓' : '✗'}
          {r.error && <div className="text-red-700">{r.error}</div>}
          {[...(r.header_diff || []), ...(r.line_diff || [])].map(([col, ours, ref]) => (
            <div key={col} dir="ltr" className="font-mono">{col}: ours={String(ours)} ref={String(ref)}</div>
          ))}
        </div>
      ))}
    </div>
  )
}

function VerifyResult({ res, size }) {
  if (!res) return null
  return (
    <div className="text-xs bg-gray-50 rounded-lg p-2 mt-2 space-y-0.5">
      {Object.entries(res.legs).map(([leg, x]) => (
        <div key={leg} className={x.present && x.lines === size ? 'text-emerald-700' : 'text-red-700'}>
          {leg === 'points' ? 'صنف النقاط' : 'صنف الاستحقاق'}: مستند {x.docnumber ?? '—'} · موجود {x.present ? '✓' : '✗'} · سطور {x.lines ?? '—'}/{size}
        </div>
      ))}
      {Object.entries(res.stock).map(([code, qty]) => (
        <div key={code}>صنف {code}: رصيد الرئيسي {n(qty)} · سطور هذه الدفعة {res.serial_rows?.[code]?.rows ?? '—'}</div>
      ))}
    </div>
  )
}

async function download(id, kind) {
  const r = await couponsApi.exportFile(id, kind)
  const url = URL.createObjectURL(r.data)
  const a = document.createElement('a')
  a.href = url
  a.download = kind === 'dataload' ? `coupon_batch_${id}_dataload.tsv` : `coupon_batch_${id}_print.xlsx`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function BatchRow({ b, canManage, writerEnabled, onChanged }) {
  const [busy, setBusy] = useState('')
  const [error, setError] = useState(null)
  const [probe, setProbe] = useState(null)
  const [verify, setVerify] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [force, setForce] = useState(false)
  const [blocked, setBlocked] = useState(null)       // validation result of a refused push

  const run = async (name, fn) => {
    setBusy(name); setError(null)
    try { await fn() } catch (e) { setError(errMsg(e)) } finally { setBusy('') }
  }
  const doPush = () => run('push', async () => {
    const r = (await couponsApi.push(b.id, { confirm: true, force })).data
    setConfirming(false)
    const refused = Object.values(r.legs || {}).find(x => x?.blocked)
    setBlocked(refused ? refused.validation : null)
    onChanged()
  })

  const leg = l => l ? (l.docnumber ? `${l.docnumber}` : l.status) : '—'
  const pending = b.status === 'generated'

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="font-bold">#{b.id}</span>
        <span className="font-mono" dir="ltr">{b.serial_from}–{b.serial_to}</span>
        <span>{b.size} كوبون</span>
        <span className="text-gray-500">صلاحية {b.expiry_from} → {b.expiry_to}</span>
        <span className={`px-2 py-0.5 rounded text-xs ${BATCH_TONE[b.status] || ''}`}>{b.status_label}</span>
        <span className="text-gray-500">مستندات SOFTECH: نقاط {leg(b.points)} · استحقاق {leg(b.served)}</span>
        <span className="text-gray-400 text-xs">{b.created_by} · {b.created_at ? new Date(b.created_at).toLocaleDateString('en-GB') : ''}</span>
      </div>
      {(b.points?.error || b.served?.error) && (
        <div className="text-xs text-red-600 mt-1">{b.points?.error || b.served?.error}</div>
      )}
      {canManage && (
        <div className="flex flex-wrap gap-2 mt-2">
          <Btn onClick={() => run('print', () => download(b.id, 'print'))} disabled={!!busy}>🖨️ ملف الطباعة</Btn>
          <Btn onClick={() => run('dl', () => download(b.id, 'dataload'))} disabled={!!busy}>ملف DataLoad</Btn>
          {pending && (
            <Btn onClick={() => run('probe', async () => setProbe((await couponsApi.probe(b.id)).data))} disabled={!!busy}>
              {busy === 'probe' ? 'جارٍ التجربة…' : 'تجربة بدون حفظ'}
            </Btn>
          )}
          {pending && !confirming && (
            <Btn variant="primary" onClick={() => setConfirming(true)} disabled={!!busy || !writerEnabled}
              title={writerEnabled ? '' : 'الإدخال في SOFTECH مغلق من الإعدادات (INVOICE_WRITER_ENABLED)'}>
              إدخال في SOFTECH
            </Btn>
          )}
          {pending && confirming && (
            <span className="flex items-center gap-2 bg-red-50 rounded-lg px-2">
              <span className="text-xs text-red-800">
                سيتم إنشاء فاتورتي شراء ({b.size} سطر لكل صنف) على المورد 1268 في الفرع الرئيسي.
              </span>
              {blocked && (
                <label className="text-xs flex items-center gap-1">
                  <input type="checkbox" checked={force} onChange={e => setForce(e.target.checked)} /> تجاوز التحذيرات
                </label>
              )}
              <Btn variant="danger" onClick={doPush} disabled={!!busy}>{busy === 'push' ? 'جارٍ الإدخال…' : 'تأكيد'}</Btn>
              <Btn onClick={() => setConfirming(false)} disabled={!!busy}>إلغاء</Btn>
            </span>
          )}
          {b.status === 'stocked' && (
            <Btn onClick={() => run('verify', async () => setVerify((await couponsApi.verify(b.id)).data))} disabled={!!busy}>
              {busy === 'verify' ? '…' : 'تحقق من SOFTECH'}
            </Btn>
          )}
        </div>
      )}
      <ErrorLine msg={error} />
      {blocked && (
        <div className="text-xs bg-amber-50 text-amber-800 rounded-lg p-2 mt-2">
          رُفض الإدخال بسبب قواعد حفظ SOFTECH:
          {[...(blocked.errors || []), ...(blocked.warnings || [])].map((m, i) => <div key={i}>• {m.message}</div>)}
        </div>
      )}
      <ProbeResult res={probe} />
      <VerifyResult res={verify} size={b.size} />
    </div>
  )
}

function BatchesView({ overview, onChanged }) {
  const [rows, setRows] = useState(null)
  const [size, setSize] = useState(overview.batch_size)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    couponsApi.batches().then(r => setRows(r.data.rows)).catch(e => setError(errMsg(e)))
  }, [])
  useEffect(load, [load])

  const generate = async () => {
    setBusy(true); setError(null)
    try { await couponsApi.generate({ size }); load(); onChanged() }
    catch (e) { setError(errMsg(e)) }
    finally { setBusy(false) }
  }

  return (
    <div className="space-y-3">
      {overview.can_manage && (
        <div className="bg-white rounded-xl border border-gray-200 p-3 flex flex-wrap items-center gap-2 text-sm">
          <span>دفعة جديدة:</span>
          <input type="number" min={1} max={overview.batch_size} value={size}
            onChange={e => setSize(Number(e.target.value))}
            className="w-24 border border-gray-300 rounded-lg px-2 py-1" />
          <span className="text-gray-500">كوبون (حد أقصى {overview.batch_size} لكل فاتورة)</span>
          <Btn variant="primary" onClick={generate} disabled={busy}>{busy ? '…' : 'توليد السريالات'}</Btn>
          <span className="text-xs text-gray-400">التوليد لا يكتب شيئًا في SOFTECH.</span>
          {!overview.writer_enabled && (
            <span className="text-xs text-amber-700 w-full">
              الإدخال في SOFTECH مغلق حاليًا (INVOICE_WRITER_ENABLED=False) — يمكن التوليد والطباعة والتجربة فقط.
            </span>
          )}
        </div>
      )}
      <ErrorLine msg={error} />
      {!rows && !error && <div className="text-sm text-gray-400">جارٍ التحميل…</div>}
      {rows?.map(b => (
        <BatchRow key={b.id} b={b} canManage={overview.can_manage} writerEnabled={overview.writer_enabled}
          onChanged={() => { load(); onChanged() }} />
      ))}
      {rows && !rows.length && <div className="text-sm text-gray-400">لا توجد دفعات.</div>}
    </div>
  )
}

// ── Tab root ─────────────────────────────────────────────────────────────────
export default function GiftCouponsTab() {
  const [ov, setOv] = useState(null)
  const [view, setView] = useState('customers')
  const [error, setError] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState(null)

  const load = useCallback(() => {
    couponsApi.overview().then(r => { setOv(r.data); setError(null) }).catch(e => setError(errMsg(e)))
  }, [])
  useEffect(load, [load])

  const sync = async () => {
    setSyncing(true); setSyncMsg(null)
    try {
      const r = (await couponsApi.sync()).data
      setSyncMsg(`تم التحديث: ${r.lines || 0} حركة (${r.no_serial || 0} بدون سريال).`)
      load()
    } catch (e) { setSyncMsg(errMsg(e)) }
    finally { setSyncing(false) }
  }

  if (error) return <ErrorLine msg={error} />
  if (!ov) return <div className="text-sm text-gray-400">جارٍ التحميل…</div>

  const noSerial30 = ov.no_serial_30d.reduce((s, r) => s + r.qty, 0)
  const views = [
    { key: 'customers', label: `عملاء تجاوزوا (${ov.customers.active_over})` },
    { key: 'no_serial', label: `بدون سريال (${n(noSerial30)} / 30 يوم)` },
    { key: 'batches',   label: `الدفعات${ov.batches_pending ? ` (${ov.batches_pending} بانتظار الإدخال)` : ''}` },
  ]

  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex flex-wrap gap-3">
        <Card label="في المخزن الرئيسي" value={n(ov.stages.stocked)} />
        <Card label="صُرف لعملاء" value={n(ov.stages.issued)} />
        <Card label="في الفروع" value={n(ov.stages.at_branch)} />
        <Card label="استُخدم" value={n(ov.stages.redeemed)} />
        <Card label="عملاء تجاوزوا (12 شهر)" value={n(ov.customers.active_over)}
          sub={`${n(ov.customers.active_excess)} كوبون زيادة`} tone="text-red-700" />
        <Card label="بدون سريال (30 يوم)" value={n(noSerial30)} tone={noSerial30 ? 'text-red-700' : 'text-gray-900'} />
        <Card label="فحص الكوبون في POS" value={ov.guard_enabled ? 'مفعّل' : 'غير مفعّل'}
          tone={ov.guard_enabled ? 'text-emerald-700' : 'text-amber-700'} />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <span>آخر تحديث: {ov.last_sync_at ? new Date(ov.last_sync_at).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }) : '—'} · آخر حركة {ov.latest_movement || '—'}</span>
        {ov.can_manage && <Btn onClick={sync} disabled={syncing}>{syncing ? 'جارٍ التحديث…' : 'تحديث من SOFTECH'}</Btn>}
        {syncMsg && <span>{syncMsg}</span>}
      </div>

      <SerialSearch />
      <GuardTest />

      <div className="flex gap-1">
        {views.map(v => (
          <button key={v.key} onClick={() => setView(v.key)}
            className={`px-3 py-1.5 text-sm rounded-lg ${view === v.key ? 'bg-gray-800 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>
            {v.label}
          </button>
        ))}
      </div>
      {view === 'customers' && <CustomersView />}
      {view === 'no_serial' && <NoSerialView />}
      {view === 'batches'   && <BatchesView overview={ov} onChanged={load} />}
    </div>
  )
}
