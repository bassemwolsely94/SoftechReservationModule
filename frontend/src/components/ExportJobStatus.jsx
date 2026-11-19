// The progress line under an export button (performance Stage 4): a progress bar while the
// server builds the file, the error with «إعادة المحاولة» when it failed. Pair with useExportJob.
import ProgressBar from './ProgressBar'

export default function ExportJobStatus({ exp, label = 'تجهيز ملف Excel', className = 'w-72' }) {
  if (!exp) return null
  return (
    <>
      {exp.running && (
        <ProgressBar className={className} pct={exp.job?.progress_pct ?? null} label={label}
          message={exp.job?.progress_msg || 'في الانتظار…'}
          since={exp.job?.created_at ? Date.parse(exp.job.created_at) : undefined} />
      )}
      {exp.error && (
        <p className="text-xs text-red-700" role="alert" data-tour="export-job-error">
          {exp.error}{' '}
          <button type="button" onClick={exp.retry} className="underline font-medium">إعادة المحاولة</button>
        </p>
      )}
    </>
  )
}
