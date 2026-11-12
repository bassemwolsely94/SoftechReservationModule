import useLangStore from '../store/langStore'

/**
 * Shown where a file used to be, after the data-retention policy removed it.
 * `date` is the server's retention_removed[field] ('YYYY-MM-DD'); renders nothing without it.
 */
export default function RemovedFileNote({ date, className = '' }) {
  const { t } = useLangStore()
  if (!date) return null
  return (
    <p className={`text-xs text-muted ${className}`}>
      {t(`أُزيل وفق سياسة الاحتفاظ بتاريخ ${date}`, `Removed under retention on ${date}`)}
    </p>
  )
}
