/**
 * AskBox — «اسأل النظام»: sends the typed question to /api/help/ask/ on demand (one
 * click, never while typing) and shows the answer written ONLY from the help text,
 * with links to the source screens. Without a model it shows the best articles.
 */
import { useEffect, useState } from 'react'
import { helpApi } from '../api/client'
import { pick } from './text'

export default function AskBox({ question, lang, screenKey, onOpen }) {
  const en = lang === 'en'
  const [state, setState] = useState({ busy: false, res: null, err: null, asked: '' })
  useEffect(() => { setState((s) => (s.asked && s.asked !== question ? { busy: false, res: null, err: null, asked: '' } : s)) }, [question])

  const ask = async () => {
    setState({ busy: true, res: null, err: null, asked: question })
    try {
      const r = await helpApi.ask({ question, lang, screen_key: screenKey || '' })
      setState({ busy: false, res: r.data, err: null, asked: question })
    } catch (e) {
      setState({ busy: false, res: null, err: e?.response?.data?.detail || (en ? 'Could not answer now.' : 'تعذّر الرد دلوقتي.'), asked: question })
    }
  }

  const { busy, res, err } = state
  if (!res && !busy && !err) {
    return (
      <button type="button" onClick={ask}
              className="w-full text-start rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-700 hover:border-brand-400">
        💬 {en ? 'Ask the system: ' : 'اسأل النظام: '}<span className="font-semibold">«{question}»</span>
      </button>
    )
  }
  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50/60 px-3 py-2.5 space-y-2">
      <div className="text-[11px] font-bold text-brand-700">💬 {en ? 'Ask the system' : 'اسأل النظام'}</div>
      {busy && <div className="text-sm text-faint">{en ? 'Reading the help guide…' : '…بيقرا دليل الاستخدام'}</div>}
      {err && <div className="text-sm text-red-600">{err}</div>}
      {res && res.answer && (
        <>
          <p className="text-sm text-content leading-7 whitespace-pre-line">{res.answer}</p>
          <p className="text-[10px] text-faint">
            {en ? 'Written only from the help guide — check the source screen below.' : 'الإجابة مكتوبة من دليل الاستخدام فقط — راجع شاشة المصدر تحت.'}
          </p>
        </>
      )}
      {res && !res.answer && (
        <p className="text-xs text-muted">
          {res.articles.length
            ? (en ? 'These help articles match your question:' : 'الشروحات دي هي الأقرب لسؤالك:')
            : (en ? 'The help guide does not cover this yet — ask your trainer or supervisor.' : 'دليل الاستخدام لسه مش بيغطي السؤال ده — اسأل المدرب أو المشرف.')}
        </p>
      )}
      {res && (() => {
        const links = res.sources.length ? res.sources : (!res.answer || !res.found ? res.articles.slice(0, 4) : [])
        return links.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {links.map((s) => (
              <button key={s.key} type="button" onClick={() => onOpen(s.key)}
                      className="text-xs border border-line bg-surface rounded-full px-2.5 py-1 text-content hover:border-brand-300">
                {s.icon} {pick(s.title, lang)}
              </button>
            ))}
          </div>
        )
      })()}
    </div>
  )
}
