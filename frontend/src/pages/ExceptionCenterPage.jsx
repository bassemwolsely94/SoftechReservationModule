/**
 * ExceptionCenterPage — POS 3.0 Wave 8.
 * A read-only manager review surface that aggregates the indirect-POS orders that need a human:
 *   • فشل الإرسال (push_failed)         — the writeback errored; retry or cancel.
 *   • متوقف أثناء الإرسال (stuck_pushing) — orphaned mid-push (writer crash); review.
 *   • عالق في الطابور (stuck_queued)     — waiting on branch connectivity; flush when back online.
 *   • بانتظار الكاشير متأخر (awaiting_cashier) — pushed long ago, still unsettled → leakage risk.
 * Reuses the existing order model/statuses + the gated /flush and /cancel endpoints. It never
 * writes to SOFTECH and never mutates a status on its own — every action goes through the
 * server-authoritative endpoints (CLAUDE.md §1/§7/§9).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api, { branchesApi } from '../api/client'
import { Badge, MetricChip, ErrorState, Icon } from '../pos/design'
import WhatsAppShareButton from '../components/WhatsAppShareButton'

const money = (v) => `${Number(v || 0).toLocaleString('en-EG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ج.م`
const fmtAge = (min) => {
  if (min == null) return '—'
  if (min < 60) return `${min} د`
  const h = Math.floor(min / 60), m = min % 60
  return h < 24 ? `${h} س${m ? ` ${m} د` : ''}` : `${Math.floor(h / 24)} ي ${h % 24} س`
}
const BUCKET_TONE = { leakage: 'blocked', push_failed: 'blocked', stuck_pushing: 'blocked', stuck_queued: 'warn', awaiting_cashier: 'warn' }
const BUCKET_ICON = { leakage: 'alert', push_failed: 'alert', stuck_pushing: 'clock', stuck_queued: 'clock', awaiting_cashier: 'store' }
const REVIEW_REASON = { pending_gone_no_final: 'اختفت الصفوف المعلّقة دون فاتورة نهائية — قد يكون حذفًا من الكاشير أو خطأ قراءة.' }

export default function ExceptionCenterPage() {
  const qc = useQueryClient()
  const [branch, setBranch] = useState('')
  const [busy, setBusy] = useState('')
  const [detailId, setDetailId] = useState(null)

  const { data: branchList } = useQuery({
    queryKey: ['branches-all'],
    queryFn: async () => (await branchesApi.listAll()).data,
    staleTime: 600000,
  })
  const branches = branchList?.results || branchList || []

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['pos-exceptions', branch],
    queryFn: async () => (await api.get('/pos-orders/exceptions/', { params: branch ? { branch } : {} })).data,
    refetchInterval: 30000,   // manager board — refresh every 30s
  })

  const flush = useMutation({
    mutationFn: (includeFailed) => api.post('/pos-orders/flush/', { include_failed: !!includeFailed }),
    onSettled: () => { setBusy(''); qc.invalidateQueries({ queryKey: ['pos-exceptions'] }) },
  })
  const cancel = useMutation({
    mutationFn: (id) => api.post(`/pos-orders/${id}/cancel/`),
    onError: (e) => alert(e?.response?.data?.detail || 'تعذّر الإلغاء'),
    onSettled: () => qc.invalidateQueries({ queryKey: ['pos-exceptions'] }),
  })

  const writerOff = data && data.writer_enabled === false
  const buckets = data?.buckets || []
  const hasAny = (data?.total_count || 0) > 0

  return (
    <div dir="rtl" className="p-4 max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2" data-tour="pos-exceptions-header">
            <Icon name="alert" size={22} /> مركز الاستثناءات — أوامر البيع
          </h1>
          <p className="text-sm text-gray-500">الأوامر التى تحتاج مراجعة: فشل الإرسال، العالقة، والمتأخرة عن التحصيل.</p>
        </div>
        <div className="flex items-center gap-2">
          <MetricChip icon="repeat" label="إجمالى الاستثناءات" value={data?.total_count ?? '—'} />
          <MetricChip icon="trending" label="قيمة معرّضة للخطر" value={money(data?.total_value_at_risk)}
                      tone={data?.total_value_at_risk > 0 ? 'warn' : 'ok'} />
          <select value={branch} onChange={e => setBranch(e.target.value)} data-tour="pos-exceptions-branch"
                  className="px-2 py-1.5 rounded border text-sm bg-white">
            <option value="">كل الفروع</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
          <button onClick={() => refetch()} disabled={isFetching}
                  className="px-3 py-1.5 rounded border text-sm flex items-center gap-1 disabled:opacity-50">
            <Icon name="repeat" size={14} /> {isFetching ? 'تحديث…' : 'تحديث'}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap" data-tour="pos-exceptions-flush">
        <button onClick={() => { setBusy('queued'); flush.mutate(false) }}
                disabled={writerOff || busy === 'queued'}
                className="px-3 py-1.5 rounded bg-blue-600 text-white text-sm flex items-center gap-1 disabled:opacity-50">
          <Icon name="truck" size={14} /> إعادة إرسال الطابور
        </button>
        <button onClick={() => { setBusy('failed'); flush.mutate(true) }}
                disabled={writerOff || busy === 'failed'}
                className="px-3 py-1.5 rounded bg-amber-600 text-white text-sm flex items-center gap-1 disabled:opacity-50">
          <Icon name="repeat" size={14} /> إعادة محاولة الطابور + الفاشل
        </button>
        {writerOff && <span className="text-xs text-red-600">الكتابة الفعلية مُعطّلة — الإجراءات معطّلة.</span>}
        {flush.data && (
          <span className="text-xs text-gray-600">
            أُرسل {flush.data.data.pushed} · لا يزال بالطابور {flush.data.data.still_queued} · فشل {flush.data.data.failed}
          </span>
        )}
      </div>

      {isLoading && <div className="text-sm text-gray-500 py-8 text-center">جارٍ التحميل…</div>}
      {error && <ErrorState title="تعذّر تحميل الاستثناءات" detail={String(error?.response?.data?.detail || error.message)}
                            actionLabel="إعادة المحاولة" onAction={() => refetch()} />}

      {data && !hasAny && (
        <div className="border rounded-lg p-8 text-center bg-green-50 border-green-200">
          <Icon name="check" size={28} className="mx-auto text-green-600" />
          <div className="mt-2 font-semibold text-green-800">لا توجد استثناءات — كل الأوامر سليمة.</div>
        </div>
      )}

      {buckets.filter(b => b.count > 0).map(b => (
        <section key={b.key} className="border rounded-lg overflow-hidden" data-tour="pos-exceptions-bucket">
          <header className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b">
            <div className="flex items-center gap-2">
              <Badge tone={BUCKET_TONE[b.key]} icon={BUCKET_ICON[b.key]} label={b.label} />
              <span className="text-sm font-bold">{b.count}</span>
            </div>
            <span className="text-xs text-gray-600">قيمة معرّضة: {money(b.value_at_risk)}</span>
          </header>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-gray-500 text-xs border-b">
                <tr>
                  <th className="text-right px-3 py-1.5">أمر</th>
                  <th className="text-right px-3 py-1.5">الفرع</th>
                  <th className="text-right px-3 py-1.5">العميل</th>
                  <th className="text-right px-3 py-1.5">القيمة</th>
                  <th className="text-right px-3 py-1.5">العمر</th>
                  <th className="text-right px-3 py-1.5">التفاصيل</th>
                  <th className="text-right px-3 py-1.5">إجراء</th>
                </tr>
              </thead>
              <tbody>
                {b.orders.map(o => (
                  <tr key={o.id} className="border-b last:border-0 hover:bg-gray-50">
                    <td className="px-3 py-1.5 font-mono">
                      POS-{o.id}
                      {o.doc_kind === 'return' && <Badge tone="info" label="مرتجع" size="xs" className="mr-1" />}
                      {o.softech_docnumber && <div className="text-xs text-gray-400">#{o.softech_docnumber}</div>}
                    </td>
                    <td className="px-3 py-1.5">{o.branch_name || o.branch}</td>
                    <td className="px-3 py-1.5">{o.customer || '—'}</td>
                    <td className="px-3 py-1.5 tabular-nums">{money(o.doc_value)}</td>
                    <td className="px-3 py-1.5 tabular-nums">{fmtAge(o.age_min)}</td>
                    <td className="px-3 py-1.5 max-w-[22rem]">
                      {o.error
                        ? <span className="text-xs text-red-600" title={o.error}>{o.error}</span>
                        : o.review_reason
                          ? <span className="text-xs text-red-600" title={REVIEW_REASON[o.review_reason] || o.review_reason}>{REVIEW_REASON[o.review_reason] || o.review_reason}</span>
                          : <span className="text-xs text-gray-500">{o.status_display}</span>}
                    </td>
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      <button onClick={() => setDetailId(o.id)} data-tour="pos-exceptions-details"
                              className="text-xs px-2 py-1 rounded border hover:bg-gray-100 ml-1">تفاصيل</button>
                      <button onClick={() => { if (confirm(`إلغاء الأمر POS-${o.id}؟`)) cancel.mutate(o.id) }}
                              disabled={cancel.isPending}
                              className="text-xs px-2 py-1 rounded border text-red-600 hover:bg-red-50 disabled:opacity-50">
                        إلغاء
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}

      {data?.thresholds && (
        <p className="text-xs text-gray-400">
          العتبات: الطابور {data.thresholds.queued_stale_min}د · الإرسال {data.thresholds.pushing_stale_min}د ·
          بانتظار الكاشير {data.thresholds.pushed_stale_min}د · تحديث تلقائى كل 30 ثانية.
        </p>
      )}

      <LostSalesTrendsPanel branch={branch} />
      <LostSalesPanel branch={branch} />

      {detailId && <OrderDetailDrawer id={detailId} onClose={() => setDetailId(null)} />}
    </div>
  )
}

/** Historical lost-sale TRENDS from the PosCancelDaily mirror — cross-branch by default (or the
 *  selected branch), over a longer window with a daily chart. Fast PG read; no branch required. */
function LostSalesTrendsPanel({ branch }) {
  const [days, setDays] = useState(30)
  const { data, isLoading, error } = useQuery({
    queryKey: ['pos-lost-trends', branch, days],
    queryFn: async () => (await api.get('/pos-orders/lost-sales-trends/',
                          { params: { days, ...(branch ? { branch } : {}) } })).data,
  })
  const s = data?.summary
  const daily = data?.daily || []
  const maxLost = Math.max(1, ...daily.map(d => d.lost_value))
  return (
    <section className="border rounded-lg overflow-hidden" data-tour="pos-exceptions-trends">
      <header className="flex items-center justify-between px-3 py-2 bg-sky-50 border-b border-sky-200">
        <div className="flex items-center gap-2">
          <Badge tone="info" icon="trending" label={`اتجاه الفرص الضائعة (تاريخى${branch ? '' : ' — كل الفروع'})`} />
          <span className="text-xs text-gray-500">من المرآة اليومية pos_cancel — يُحدَّث ليلاً</span>
        </div>
        <select value={days} onChange={e => setDays(Number(e.target.value))}
                className="px-2 py-1 rounded border text-xs bg-white">
          <option value={30}>آخر 30 يوم</option>
          <option value={60}>آخر 60 يوم</option>
          <option value={90}>آخر 90 يوم</option>
        </select>
      </header>

      {isLoading && <div className="text-sm text-gray-500 py-6 text-center">جارٍ التحميل…</div>}
      {error && <div className="text-sm text-red-600 p-3">تعذّر تحميل الاتجاه: {String(error?.response?.data?.detail || error.message)}</div>}

      {s && (
        <div className="p-3 space-y-3">
          <div className="flex flex-wrap gap-2">
            <MetricChip icon="trending" label="إجمالى القيمة الضائعة" value={money(s.lost_value)}
                        tone={s.lost_value > 0 ? 'warn' : 'ok'} />
            <MetricChip icon="x" label="أسطر مُسعّرة أُلغيت" value={s.priced_events} />
            <MetricChip icon="repeat" label="إجمالى الأحداث" value={s.events} />
          </div>

          {/* daily lost-value bars (inline SVG, theme-aware via currentColor) */}
          {daily.length > 0 && (
            <div className="border rounded p-2">
              <div className="text-xs font-semibold text-gray-600 mb-2">القيمة الضائعة يوميًا</div>
              <div className="flex items-end gap-0.5 h-24" dir="ltr">
                {daily.map(d => (
                  <div key={d.day} className="flex-1 flex flex-col justify-end group relative"
                       title={`${d.day}: ${money(d.lost_value)} · ${d.priced_events} سطر`}>
                    <div className="bg-sky-500/70 hover:bg-sky-600 rounded-t"
                         style={{ height: `${Math.max(2, (d.lost_value / maxLost) * 100)}%` }} />
                  </div>
                ))}
              </div>
              <div className="flex justify-between text-[10px] text-gray-400 mt-1" dir="ltr">
                <span>{daily[0]?.day}</span><span>{daily[daily.length - 1]?.day}</span>
              </div>
            </div>
          )}

          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <div className="text-xs font-semibold text-gray-600 mb-1">أكثر الأصناف ضياعًا (المدة كاملة)</div>
              <div className="overflow-x-auto border rounded max-h-72 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500 sticky top-0"><tr>
                    <th className="text-right px-2 py-1">الصنف</th>
                    <th className="text-right px-2 py-1">مرات</th>
                    <th className="text-right px-2 py-1">مُسعّر</th>
                    <th className="text-right px-2 py-1">قيمة ضائعة</th>
                  </tr></thead>
                  <tbody>
                    {(data.top_items || []).map(it => (
                      <tr key={it.item_code} className="border-t">
                        <td className="px-2 py-1">{it.item_name || it.item_code}</td>
                        <td className="px-2 py-1 tabular-nums">{it.events}</td>
                        <td className="px-2 py-1 tabular-nums">{it.priced_events}</td>
                        <td className="px-2 py-1 tabular-nums font-medium">{money(it.lost_value)}</td>
                      </tr>
                    ))}
                    {!(data.top_items || []).length && (
                      <tr><td colSpan={4} className="px-2 py-3 text-center text-gray-400">لا توجد بيانات — شغِّل sync_pos_cancel أولاً.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-gray-600 mb-1">حسب الفرع</div>
              <div className="overflow-x-auto border rounded max-h-72 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500 sticky top-0"><tr>
                    <th className="text-right px-2 py-1">الفرع</th>
                    <th className="text-right px-2 py-1">أسطر مُسعّرة</th>
                    <th className="text-right px-2 py-1">قيمة ضائعة</th>
                  </tr></thead>
                  <tbody>
                    {(data.by_branch || []).map(b => (
                      <tr key={b.branch_code} className="border-t">
                        <td className="px-2 py-1">{b.branch_code}</td>
                        <td className="px-2 py-1 tabular-nums">{b.priced_events}</td>
                        <td className="px-2 py-1 tabular-nums font-medium">{money(b.lost_value)}</td>
                      </tr>
                    ))}
                    {!(data.by_branch || []).length && (
                      <tr><td colSpan={3} className="px-2 py-3 text-center text-gray-400">—</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

/** Lost-sales / «المبيعات غير المخزنة» — read-only aggregates from SOFTECH pos_cancel for one branch:
 *  items customers asked about but weren't sold, and cancellations by cashier. Needs a branch selected. */
function LostSalesPanel({ branch }) {
  const [days, setDays] = useState(14)
  const { data, isLoading, error } = useQuery({
    queryKey: ['pos-lost-sales', branch, days],
    queryFn: async () => (await api.get('/pos-orders/lost-sales/', { params: { branch, days } })).data,
    enabled: !!branch,
  })
  if (!branch) {
    return (
      <section className="border rounded-lg p-4 bg-gray-50 text-sm text-gray-500 flex items-center gap-2">
        <Icon name="search" size={16} /> اختر فرعًا بالأعلى لعرض «المبيعات غير المخزنة» (الأصناف المطلوبة ولم تُبَع + الإلغاءات).
      </section>
    )
  }
  const s = data?.summary
  return (
    <section className="border rounded-lg overflow-hidden">
      <header className="flex items-center justify-between px-3 py-2 bg-amber-50 border-b border-amber-200">
        <div className="flex items-center gap-2">
          <Badge tone="warn" icon="alert" label="المبيعات غير المخزنة — فرص ضائعة" />
          <span className="text-xs text-gray-500">أصناف دخلت الشاشة ولم تُرحَّل (سجل الإلغاء pos_cancel)</span>
        </div>
        <select value={days} onChange={e => setDays(Number(e.target.value))}
                className="px-2 py-1 rounded border text-xs bg-white">
          <option value={7}>آخر 7 أيام</option>
          <option value={14}>آخر 14 يوم</option>
          <option value={30}>آخر 30 يوم</option>
        </select>
      </header>

      {isLoading && <div className="text-sm text-gray-500 py-6 text-center">جارٍ التحميل…</div>}
      {error && <div className="text-sm text-red-600 p-3">تعذّر تحميل السجل: {String(error?.response?.data?.detail || error.message)}</div>}

      {s && (
        <div className="p-3 space-y-3">
          <div className="flex flex-wrap gap-2">
            <MetricChip icon="trending" label="قيمة معرّضة (أصناف مُسعّرة أُلغيت)" value={money(s.lost_value)}
                        tone={s.lost_value > 0 ? 'warn' : 'ok'} />
            <MetricChip icon="x" label="أسطر مُسعّرة أُلغيت" value={s.priced_events} />
            <MetricChip icon="repeat" label="إجمالى الأحداث" value={s.events} />
            <MetricChip icon="usercheck" label="كاشير" value={s.distinct_cashiers} />
          </div>

          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <div className="text-xs font-semibold text-gray-600 mb-1">أكثر الأصناف ضياعًا</div>
              <div className="overflow-x-auto border rounded max-h-72 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500 sticky top-0"><tr>
                    <th className="text-right px-2 py-1">الصنف</th>
                    <th className="text-right px-2 py-1">مرات</th>
                    <th className="text-right px-2 py-1">مُسعّر</th>
                    <th className="text-right px-2 py-1">قيمة ضائعة</th>
                  </tr></thead>
                  <tbody>
                    {(data.top_items || []).map(it => (
                      <tr key={it.itemcode} className="border-t">
                        <td className="px-2 py-1">{it.name} <span className="text-gray-400">#{it.itemcode}</span></td>
                        <td className="px-2 py-1 tabular-nums">{it.events}</td>
                        <td className="px-2 py-1 tabular-nums">{it.priced_events}</td>
                        <td className="px-2 py-1 tabular-nums">{money(it.lost_value)}</td>
                      </tr>
                    ))}
                    {!data.top_items?.length && <tr><td colSpan={4} className="text-center text-gray-400 py-3">لا يوجد</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <div className="text-xs font-semibold text-gray-600 mb-1">الإلغاءات حسب الكاشير</div>
              <div className="overflow-x-auto border rounded max-h-72 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500 sticky top-0"><tr>
                    <th className="text-right px-2 py-1">الكاشير</th>
                    <th className="text-right px-2 py-1">أحداث</th>
                    <th className="text-right px-2 py-1">مُسعّر</th>
                    <th className="text-right px-2 py-1">قيمة</th>
                  </tr></thead>
                  <tbody>
                    {(data.by_cashier || []).map(c => (
                      <tr key={c.usercode} className="border-t">
                        <td className="px-2 py-1">{c.name}</td>
                        <td className="px-2 py-1 tabular-nums">{c.events}</td>
                        <td className="px-2 py-1 tabular-nums">{c.priced_events}</td>
                        <td className="px-2 py-1 tabular-nums">{money(c.lost_value)}</td>
                      </tr>
                    ))}
                    {!data.by_cashier?.length && <tr><td colSpan={4} className="text-center text-gray-400 py-3">لا يوجد</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <p className="text-xs text-gray-400">
            «مُسعّر» = صنف دخل بسعر ثم أُلغِى قبل الحفظ (فرصة بيع حقيقية ضائعة). القيمة = مجموع أسعار الأسطر المُلغاة.
          </p>
        </div>
      )}
    </section>
  )
}

/** Read-only drill-down: the full order (lines, payments, error, readback) from the existing detail API. */
function OrderDetailDrawer({ id, onClose }) {
  const { data: o, isLoading } = useQuery({
    queryKey: ['pos-order', id],
    queryFn: async () => (await api.get(`/pos-orders/${id}/`)).data,
  })
  return (
    <div className="fixed inset-0 bg-black/40 flex justify-start z-50" onClick={onClose}>
      <div dir="rtl" className="bg-white w-[34rem] max-w-[92vw] h-full overflow-auto p-4 shadow-xl"
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold flex items-center gap-2"><Icon name="search" size={18} /> تفاصيل الأمر POS-{id}</h2>
          <div className="flex items-center gap-2">
            <WhatsAppShareButton type="pos_order" docId={id} size="sm" label="إيصال واتساب" />
            <button onClick={onClose} className="text-gray-400 hover:text-gray-700"><Icon name="x" size={18} /></button>
          </div>
        </div>
        {isLoading && <div className="text-sm text-gray-500 py-6 text-center">جارٍ التحميل…</div>}
        {o && (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <Field label="الحالة" value={o.status} />
              <Field label="النوع" value={o.doc_kind} />
              <Field label="القناة" value={o.channel} />
              <Field label="العميل" value={o.softech_pic || o.customer_name || '—'} />
              <Field label="رقم SOFTECH" value={o.softech_docnumber || '—'} />
              <Field label="القيمة" value={money(o.doc_value)} />
            </div>
            {o.erp_error && (
              <div className="bg-red-50 border border-red-200 rounded p-2">
                <div className="text-xs font-semibold text-red-700 mb-1">خطأ الإرسال</div>
                <pre className="text-xs whitespace-pre-wrap text-red-800">{o.erp_error}</pre>
              </div>
            )}
            <div>
              <div className="text-xs font-semibold text-gray-600 mb-1">الأصناف ({o.lines?.length || 0})</div>
              <div className="overflow-x-auto border rounded">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500"><tr>
                    <th className="text-right px-2 py-1">الصنف</th><th className="text-right px-2 py-1">كمية</th>
                    <th className="text-right px-2 py-1">سعر</th><th className="text-right px-2 py-1">خصم%</th>
                  </tr></thead>
                  <tbody>
                    {(o.lines || []).map((l, i) => (
                      <tr key={i} className="border-t">
                        <td className="px-2 py-1">{l.item_name || l.softech_itemcode}</td>
                        <td className="px-2 py-1 tabular-nums">{l.qty}</td>
                        <td className="px-2 py-1 tabular-nums">{Number(l.item_sale_price || 0).toFixed(2)}</td>
                        <td className="px-2 py-1 tabular-nums">{l.cust_discp || 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            {(o.payments?.length > 0) && (
              <div>
                <div className="text-xs font-semibold text-gray-600 mb-1">السداد</div>
                <ul className="text-xs space-y-0.5">
                  {o.payments.map((p, i) => (
                    <li key={i} className="flex justify-between border-b py-0.5">
                      <span>{p.pay_type}</span><span className="tabular-nums">{money(p.amount)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Field({ label, value }) {
  return (
    <div className="border rounded px-2 py-1">
      <div className="text-[10px] text-gray-400">{label}</div>
      <div className="font-medium">{String(value ?? '—')}</div>
    </div>
  )
}
