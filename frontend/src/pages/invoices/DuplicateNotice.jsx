/** Inline amber notice shown inside the upload form when the same file was uploaded before.
 *  No modal: «فتح» opens the earlier one, «رفع على أي حال» resends with allow_duplicate=1. */
export default function DuplicateNotice({ dup, busy, onOpen, onContinue }) {
  return (
    <div className="mt-3 text-xs text-amber-800 bg-amber-50 px-3 py-2 rounded-lg" role="status">
      رفعت هذا الملف من قبل: {dup.label} ({dup.status_label}){' · '}
      <button type="button" onClick={onOpen} className="font-medium underline hover:text-amber-900">فتح</button>
      {' · '}
      <button type="button" onClick={onContinue} disabled={busy}
        className="font-medium underline hover:text-amber-900 disabled:opacity-50">رفع على أي حال</button>
    </div>
  )
}
