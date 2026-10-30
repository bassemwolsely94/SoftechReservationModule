/**
 * NoteHints — gentle hints under the «إيه الجديد للمستخدمين؟» field while a trainer types
 * (POST /api/help/notes-check/, rules in apps/help/notecheck.py): a big edit with no note,
 * a note that is only generic words, or the same change worded differently elsewhere
 * («استخدمها» copies that wording in). Never blocks saving; no popups.
 */
import { useEffect, useState } from 'react'
import { helpApi } from '../api/client'

export function useNoteHints(kind, key, note, draft) {
  const [hints, setHints] = useState([])
  const draftJson = JSON.stringify(draft ?? null)
  useEffect(() => {
    if (!kind || !key || draft == null) { setHints([]); return undefined }
    let live = true
    const t = setTimeout(() => {
      helpApi.checkNote(kind, key, note, JSON.parse(draftJson))
        .then((r) => { if (live) setHints(r.data.hints || []) })
        .catch(() => { if (live) setHints([]) })
    }, 700)
    return () => { live = false; clearTimeout(t) }
  }, [kind, key, note, draftJson])  // eslint-disable-line react-hooks/exhaustive-deps
  return hints
}

export default function NoteHints({ hints, onUse }) {
  if (!hints?.length) return null
  return (
    <div className="space-y-1" data-tour="general-help-note-hints">
      {hints.map((h, i) => (
        <div key={i} className="text-[11px] leading-5 text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1">
          💡 {h.text}
          {h.suggestion && (
            <button type="button" onClick={() => onUse(h.suggestion)} className="ms-2 font-semibold underline">استخدمها</button>
          )}
        </div>
      ))}
    </div>
  )
}
