import { useEffect, useState } from 'react'
import { helpApi } from '../api/client'
import { label } from './text'

/** "Was this helpful?" — one vote + optional comment, sent to the trainers' list. */
export default function HelpFeedback({ screenKey, tab, lang }) {
  const [vote, setVote] = useState(null)       // null | true | false
  const [comment, setComment] = useState('')
  const [sent, setSent] = useState(false)

  useEffect(() => { setVote(null); setComment(''); setSent(false) }, [screenKey])

  const send = async (helpful, text = '') => {
    try {
      await helpApi.feedback({ screen_key: screenKey, tab: tab || '', helpful, comment: text, lang })
      setSent(true)
    } catch { /* feedback is best-effort */ }
  }

  if (sent) return <div className="text-xs text-emerald-700">{label('thanks', lang)}</div>

  if (vote === false) {
    return (
      <div className="space-y-1.5">
        <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500}
                  placeholder={label('whatsMissing', lang)} autoFocus
                  className="w-full text-sm border border-line rounded-lg px-2 py-1.5 bg-surface text-content" />
        <button type="button" onClick={() => send(false, comment)}
                className="text-xs bg-brand-600 text-white rounded-lg px-3 py-1">{label('send', lang)}</button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-muted">{label('wasHelpful', lang)}</span>
      <button type="button" onClick={() => { setVote(true); send(true) }}
              className="border border-line rounded-full px-2.5 py-0.5 hover:bg-emerald-50 hover:border-emerald-300">{label('yes', lang)}</button>
      <button type="button" onClick={() => setVote(false)}
              className="border border-line rounded-full px-2.5 py-0.5 hover:bg-red-50 hover:border-red-300">{label('no', lang)}</button>
    </div>
  )
}
