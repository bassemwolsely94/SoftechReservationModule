// C24 — one calm line after a bulk run: how many went through, and each refusal with its reason.
export default function BulkResultNote({ result, verb = 'تم', labelOf = id => `#${id}`, onClose, testId = 'bulk-result' }) {
  if (!result) return null
  const { done = [], failed = [] } = result
  return (
    <div role="status" data-testid={testId} className="mb-3 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
      <span className={failed.length ? 'text-amber-700' : 'text-green-700'}>
        {verb} {done.length}{failed.length ? ` · تعذّر ${failed.length} (ما زالت محددة):` : ''}
      </span>
      {onClose && <button type="button" onClick={onClose} className="ms-2 text-xs text-gray-400 hover:text-gray-600">✕</button>}
      {failed.length > 0 && (
        <ul className="mt-1 list-disc ps-5 text-xs text-gray-600">
          {failed.map(f => <li key={f.id}>{labelOf(f.id)} — {f.detail}</li>)}
        </ul>
      )}
    </div>
  )
}
