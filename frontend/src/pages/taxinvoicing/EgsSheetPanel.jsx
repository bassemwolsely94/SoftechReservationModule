/**
 * «ملف أكواد الإيصالات (المحصّل)» — the Invoicer's bulk EGS sheet (ElRezeiky_Bulk_EGS_Items.xlsx), batch S3. Display
 * only: the server builds each version (in the background, one at a time), checks it, and says why an item was left
 * out or a build refused. This panel shows the latest version, starts a build, polls only while one runs, and
 * downloads the full file or the new rows.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { ActionMsg, Btn, Failed, fmtInt, fmtTime, Loading, Notice, Section, useAction } from './ui'

const POLL_MS = 4000
const FULL_NAME = 'ElRezeiky_Bulk_EGS_Items.xlsx'      // the name the Invoicer reads
const SOURCE = { seed: 'ملف المالك', build: 'بناء' }
export const REMINDER = 'بعد استبدال الملف في D:\\invoicer_mini أغلق Excel — الملف المفتوح يوقف رفع الإيصالات'

function save(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function BuildState({ build }) {
  const s = build?.state
  if (!s || s === 'idle') return null
  if (s === 'running') {
    return <div role="status" className="text-xs text-primary">⏳ جارٍ بناء الملف… بدأ {fmtTime(build.started_at)} — يأخذ دقيقة أو اثنتين</div>
  }
  const when = <span className="text-gray-400"> · {fmtTime(build.finished_at)}{build.by ? ` · ${build.by}` : ''}</span>
  if (s === 'built') return <div role="status" className="text-xs text-emerald-700">✅ بُنيت النسخة {build.version}{when}</div>
  if (s === 'unchanged') return <div role="status" className="text-xs text-gray-600">لا جديد يُكتب — النسخة {build.version} كما هي{when}</div>
  if (s === 'refused') {
    return (
      <Notice tone="red" data-testid="egs-sheet-refused">
        <div className="font-semibold">رُفض البناء ولم تُحفظ نسخة{when}</div>
        <ul className="mt-1 list-disc ms-4 text-xs">{(build.refused || []).map((r, n) => <li key={n}>{r}</li>)}</ul>
      </Notice>
    )
  }
  return <Notice tone="red">تعذّر البناء: {build.error}{when}</Notice>
}

export default function EgsSheetPanel() {
  const act = useAction()
  const [showSkipped, setShowSkipped] = useState(false)
  const q = useQuery({
    queryKey: ['tax-invoicing', 'egs-sheet'],
    queryFn: () => taxInvoicingApi.egsSheet().then(r => r.data),
    refetchInterval: query => (query.state.data?.build?.state === 'running' ? POLL_MS : false),
  })
  const d = q.data
  const v = d?.versions?.[0]
  const running = d?.build?.state === 'running'
  const skipped = d?.pending?.skipped || []
  const download = kind => act.run(() => taxInvoicingApi.egsSheetDownload(v.number, kind), r => {
    save(r instanceof Blob ? r : new Blob([r]), kind === 'full' ? FULL_NAME : `ElRezeiky_Bulk_EGS_Items_v${v.number}_new.xlsx`)
    return 'تم التنزيل'
  })

  return (
    <Section title="ملف أكواد الإيصالات (المحصّل)" data-tour="tax-invoicing-queue-egs-sheet"
      hint={v ? `النسخة ${v.number} · ${fmtTime(v.built_at)} · ${SOURCE[v.source] || v.source}${v.built_by ? ` · ${v.built_by}` : ''}` : ''}
      actions={d?.can_build && v && (
        <>
          <Btn variant="primary" disabled={act.pending || running} onClick={() => act.run(() => taxInvoicingApi.egsSheetBuild({}), 'بدأ البناء')}>
            {running ? 'جارٍ البناء…' : 'بناء نسخة جديدة'}
          </Btn>
          <Btn disabled={act.pending || !v.has_file} title={v.has_file ? '' : 'ملف هذه النسخة لم يعد محفوظاً'}
            onClick={() => download('full')}>تنزيل الملف كاملاً</Btn>
          <Btn disabled={act.pending || !v.has_file || !(v.added + v.coded)} onClick={() => download('new')}>الصفوف الجديدة فقط</Btn>
        </>
      )}>
      {q.isLoading ? <Loading /> : q.error ? <Failed error={q.error} /> : !v ? (
        <p className="text-sm text-gray-500">لا توجد نسخة محفوظة من ملف الأكواد — يُخزَّن ملف المالك أولاً (egs_sheet_seed).</p>
      ) : (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-gray-700">
            <span>صفوف مكوّدة <b>{fmtInt(v.coded_rows)}</b> من {fmtInt(v.total_rows)}</span>
            <span>أُضيف في هذه النسخة <b>{fmtInt(v.added)}</b></span>
            <span>كُوّد في صفه <b>{fmtInt(v.coded)}</b></span>
            <span>تُرك في هذه النسخة <b>{fmtInt(v.skipped?.length)}</b></span>
            <span>جاهز للبناء الآن <b>{fmtInt(d.pending.ready)}</b></span>
            <button type="button" className="text-primary disabled:text-gray-400" disabled={!skipped.length}
              onClick={() => setShowSkipped(x => !x)}>
              متروك الآن <b>{fmtInt(skipped.length)}</b>{skipped.length ? (showSkipped ? ' ▲' : ' ▼') : ''}
            </button>
          </div>
          {showSkipped && skipped.length > 0 && (
            <ul aria-label="الأصناف المتروكة" className="max-h-48 overflow-y-auto border border-gray-200 rounded-md divide-y divide-gray-100 text-xs">
              {skipped.map(s => (
                <li key={s.itemcode} className="px-2 py-1"><span className="font-mono">{s.itemcode}</span> — {s.why}</li>
              ))}
            </ul>
          )}
          <BuildState build={d.build} />
          <Notice tone="amber">{REMINDER}</Notice>
          <p className="text-xs text-gray-500">القيم في الأعمدة L–P مكتوبة كأرقام وليست معادلات.</p>
        </div>
      )}
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
    </Section>
  )
}
