/**
 * Growth tab (النمو) of /data-health: sizes, the size-over-time chart, the days-to-level forecast, and
 * sortable grids for tables, upload types, folders and what the rules did. Display only — every number
 * comes from GET /api/data-health/growth/.
 */
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { TD, TH, fmtBytes, fmtDate, fmtGrowth, fmtInt } from './format'

const DB_COLOR = 'rgb(var(--c-brand-sky))'
const MEDIA_COLOR = '#d97706'

function Tile({ label, value, sub, tone = '' }) {
  return (
    <div className={`card p-4 ${tone}`}>
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-xl font-bold text-gray-900 mt-1 tabular-nums" dir="ltr">{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  )
}

function forecastText(f, current) {
  if (!f || f.daily_bytes == null) return { value: '—', sub: 'يحتاج ٧ أيام قياس على الأقل' }
  if (f.days_to_level == null) {
    return { value: '—', sub: f.daily_bytes <= 0 ? 'الحجم لا يزيد حاليًا' : 'لا توجد بيانات عن مساحة القرص' }
  }
  const used = current?.disk_total_bytes ? 100 - Math.round((current.disk_free_bytes / current.disk_total_bytes) * 100) : null
  return {
    value: `${fmtInt(f.days_to_level)} يوم`,
    sub: `حتى امتلاء ${f.level_percent}% من القرص بمعدل ${fmtBytes(f.daily_bytes)} يوميًا${used != null ? ` (مستخدم الآن ${used}%)` : ''}`,
  }
}

/** Database and media size over time; both lines labelled at their end, no legend. */
function SizeChart({ series }) {
  if (!series || series.length < 2) {
    return <p className="text-sm text-gray-500 py-6 text-center">الرسم يظهر بعد يومين من القياس على الأقل.</p>
  }
  const W = 720, H = 220, PAD = { top: 14, right: 84, bottom: 24, left: 56 }
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const maxV = Math.max(1, ...series.map(s => Math.max(s.db_bytes, s.media_bytes)))
  const x = i => PAD.left + (i / (series.length - 1)) * innerW
  const y = v => PAD.top + innerH - (v / maxV) * innerH
  const line = key => series.map((s, i) => `${x(i)},${y(s[key])}`).join(' ')
  const last = series[series.length - 1]
  const step = Math.max(1, Math.floor(series.length / 6))
  const ticks = [0, 0.5, 1].map(f => f * maxV)
  // end labels: keep them at least 12px apart when the two lines finish close together
  let dbLabelY = y(last.db_bytes) + 4
  let mediaLabelY = y(last.media_bytes) + 4
  if (Math.abs(dbLabelY - mediaLabelY) < 12) {
    const mid = (dbLabelY + mediaLabelY) / 2
    const dbAbove = last.db_bytes >= last.media_bytes
    dbLabelY = mid + (dbAbove ? -6 : 6)
    mediaLabelY = mid + (dbAbove ? 6 : -6)
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" dir="ltr" role="img"
         aria-label="حجم قاعدة البيانات والملفات المرفوعة عبر الأيام">
      {ticks.map(t => (
        <g key={t}>
          <line x1={PAD.left} x2={PAD.left + innerW} y1={y(t)} y2={y(t)} stroke="rgb(var(--c-line))" strokeWidth="1" />
          <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="rgb(var(--c-muted))">{fmtBytes(t)}</text>
        </g>
      ))}
      <polyline points={line('db_bytes')} fill="none" stroke={DB_COLOR} strokeWidth="2" strokeLinejoin="round" />
      <polyline points={line('media_bytes')} fill="none" stroke={MEDIA_COLOR} strokeWidth="2" strokeLinejoin="round" />
      <text x={x(series.length - 1) + 6} y={dbLabelY} fontSize="11" fill={DB_COLOR}>قاعدة البيانات</text>
      <text x={x(series.length - 1) + 6} y={mediaLabelY} fontSize="11" fill={MEDIA_COLOR}>الملفات</text>
      {series.map((s, i) => (i % step === 0 ? (
        <text key={s.day} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="rgb(var(--c-muted))">{s.day.slice(5)}</text>
      ) : null))}
    </svg>
  )
}

function TablesGrid({ rows }) {
  const { sorted, headerProps: h } = useSortableRows(rows, { persistKey: 'data-health-tables' })
  if (!rows.length) return <p className="text-sm text-gray-500">لم تُقَس أحجام الجداول بعد.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-50"><tr>
          <SortTh {...h('table', 'text')} className={TH}>الجدول</SortTh>
          <SortTh {...h('total_bytes', 'number')} className={TH}>الحجم</SortTh>
          <SortTh {...h('growth_bytes', 'number')} className={TH}>النمو (٣٠ يوم)</SortTh>
          <SortTh {...h('empty_bytes', 'number')} className={TH}>مساحة فارغة تقديرية</SortTh>
          <SortTh {...h('row_estimate', 'number')} className={TH}>عدد السطور (تقريبي)</SortTh>
          <SortTh {...h('rule_label_ar', 'text')} className={TH}>القاعدة</SortTh>
        </tr></thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(t => (
            <tr key={t.table}>
              <td className={`${TD} font-mono text-xs`} dir="ltr">{t.table}</td>
              <td className={`${TD} tabular-nums`} dir="ltr">{fmtBytes(t.total_bytes)}</td>
              <td className={`${TD} tabular-nums`} dir="ltr">{fmtGrowth(t.growth_bytes)}</td>
              <td className={`${TD} tabular-nums`} dir="ltr">{t.empty_bytes ? fmtBytes(t.empty_bytes) : '—'}</td>
              <td className={`${TD} tabular-nums`}>{fmtInt(t.row_estimate)}</td>
              <td className={TD}>
                {t.classified ? t.rule_label_ar
                  : <span className="inline-block rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-xs text-amber-800">غير مصنف</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MediaGrid({ rows, keyName, title, persistKey }) {
  const { sorted, headerProps: h } = useSortableRows(rows, { persistKey })
  if (!rows.length) return <p className="text-sm text-gray-500">لا توجد ملفات مقاسة بعد.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-50"><tr>
          <SortTh {...h(keyName === 'key' ? 'label_ar' : keyName, 'text')} className={TH}>{title}</SortTh>
          <SortTh {...h('bytes', 'number')} className={TH}>الحجم</SortTh>
          <SortTh {...h('files', 'number')} className={TH}>عدد الملفات</SortTh>
          <SortTh {...h('growth_bytes', 'number')} className={TH}>النمو (٣٠ يوم)</SortTh>
        </tr></thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(r => (
            <tr key={r[keyName]}>
              <td className={TD}>
                {keyName === 'key'
                  ? (r.label_ar || <span className="font-mono text-xs" dir="ltr">{r.key}</span>)
                  : <span className="font-mono text-xs" dir="ltr">{r.folder}</span>}
              </td>
              <td className={`${TD} tabular-nums`} dir="ltr">{fmtBytes(r.bytes)}</td>
              <td className={`${TD} tabular-nums`}>{fmtInt(r.files)}</td>
              <td className={`${TD} tabular-nums`} dir="ltr">{fmtGrowth(r.growth_bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RemovedGrid({ rows }) {
  const { sorted, headerProps: h } = useSortableRows(rows, { persistKey: 'data-health-removed' })
  if (!rows.length) return <p className="text-sm text-gray-500">لم تحذف القواعد شيئًا في آخر ٣٠ يومًا.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-50"><tr>
          <SortTh {...h('label_ar', 'text')} className={TH}>القاعدة</SortTh>
          <SortTh {...h('count', 'number')} className={TH}>العدد</SortTh>
          <SortTh {...h('bytes', 'number')} className={TH}>الحجم</SortTh>
        </tr></thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(r => (
            <tr key={r.rule_key}>
              <td className={TD}>{r.label_ar}</td>
              <td className={`${TD} tabular-nums`}>{fmtInt(r.count)}</td>
              <td className={`${TD} tabular-nums`} dir="ltr">{fmtBytes(r.bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Section({ title, children, ...rest }) {
  return (
    <section className="card p-4 space-y-3" {...rest}>
      <h2 className="font-semibold text-gray-800">{title}</h2>
      {children}
    </section>
  )
}

export default function GrowthTab({ query }) {
  if (query.isLoading) return <p className="text-sm text-gray-500">جارٍ التحميل…</p>
  if (query.isError) return <p className="text-sm text-red-600">تعذر تحميل البيانات.</p>
  const d = query.data
  const c = d.current || {}
  const f = forecastText(d.forecast, c)
  const m = d.measures || {}
  return (
    <div className="space-y-4">
      {!d.as_of && (
        <p className="card p-3 text-sm text-gray-600">لا يوجد قياس بعد. يُؤخذ القياس يوميًا مع الصيانة الليلية، أو اضغط «تحديث الآن».</p>
      )}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-tour="data-health-main-tiles">
        <Tile label="قاعدة البيانات" value={fmtBytes(c.db_bytes)} />
        <Tile label="الملفات المرفوعة" value={fmtBytes(c.media_bytes)} sub={c.media_files != null ? `${fmtInt(c.media_files)} ملف` : null} />
        <Tile label="مساحة فارغة تقديرية" value={fmtBytes(c.empty_bytes)} sub="داخل الجداول، يمكن استردادها" />
        <Tile label="أيام حتى المستوى" value={f.value} sub={f.sub} />
      </div>
      <p className="text-xs text-gray-500">
        ملفات محجوزة الآن: {fmtInt(c.held_files)} ({fmtBytes(c.held_bytes)}) ·
        مساحة القرص الحرة: {c.disk_total_bytes ? `${fmtBytes(c.disk_free_bytes)} من ${fmtBytes(c.disk_total_bytes)}` : 'غير معروفة'}
      </p>

      <Section title="الحجم عبر الأيام" data-tour="data-health-main-chart">
        <SizeChart series={d.series} />
      </Section>

      <Section title="الجداول" data-tour="data-health-main-tables">
        <TablesGrid rows={d.tables || []} />
      </Section>

      <div className="grid lg:grid-cols-2 gap-4">
        <Section title="أنواع الملفات المرفوعة">
          <MediaGrid rows={d.types || []} keyName="key" title="النوع" persistKey="data-health-types" />
        </Section>
        <Section title="المجلدات">
          <MediaGrid rows={d.folders || []} keyName="folder" title="المجلد" persistKey="data-health-folders" />
        </Section>
      </div>

      <Section title="ما فعلته القواعد (آخر ٣٠ يومًا)" data-tour="data-health-main-measures">
        <RemovedGrid rows={m.removed || []} />
        <p className="text-xs text-gray-500">
          ملفات مسترجعة: {fmtInt(m.restores)} · أيام لم تكتمل فيها الصيانة اليومية: {fmtInt(m.missed_retention_days)}
        </p>
      </Section>
      <p className="text-xs text-gray-400">آخر قياس {fmtDate(d.as_of, true)}</p>
    </div>
  )
}
