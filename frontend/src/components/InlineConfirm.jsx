// D-25 / FE-9 — calm replacements for the native browser dialogs (CLAUDE.md rule 11).
//
//   <ConfirmButton onConfirm={…}>حذف</ConfirmButton>
//       an inline two-step button: the first click turns the same button red («تأكيد؟») for 4 s,
//       a second click inside that window runs the action. No dialog, no focus jump.
//
//   const { confirm, ask, ui } = useConfirm()   …   return <>{ui} … </>
//       for a check inside a handler, where the message carries details (counts, codes, SOFTECH
//       writes). `await confirm(msg)` → true/false; `await ask(msg)` → the typed text or null
//       (replaces prompt()). It shows a small non-modal bar at the bottom of the screen — no
//       backdrop, the page stays usable — Enter confirms, Esc cancels.
//
// A destructive action keeps an explicit second step either way; only the native dialog goes.
// Plain `alert()` messages move to the existing toasts (useToast in ui.jsx).
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export const ARM_MS = 4000

export function ConfirmButton({
  onConfirm, children, confirmLabel = 'تأكيد؟', className = '', armedClassName = '',
  timeout = ARM_MS, disabled, title, type = 'button', ...rest
}) {
  const [armed, setArmed] = useState(false)
  const timer = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])

  const onClick = (e) => {
    e.stopPropagation()
    if (disabled) return
    if (!armed) {
      setArmed(true)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setArmed(false), timeout)
      return
    }
    clearTimeout(timer.current)
    setArmed(false)
    onConfirm?.(e)
  }

  return (
    <button
      type={type}
      {...rest}
      disabled={disabled}
      title={armed ? 'اضغط مرة ثانية للتأكيد' : title}
      aria-live="polite"
      data-armed={armed ? '1' : '0'}
      onClick={onClick}
      className={armed
        ? (armedClassName || `${className} !bg-red-600 !text-white !border-red-600`)
        : className}
    >
      {armed ? confirmLabel : children}
    </button>
  )
}

function ConfirmBar({ req, onDone }) {
  const [text, setText] = useState(req.input?.initial ?? '')
  const inputRef = useRef(null)
  const okRef = useRef(null)
  const needsText = !!req.input?.required
  const blocked = needsText && !text.trim()

  useEffect(() => {
    (req.input ? inputRef.current : okRef.current)?.focus()
  }, [req])

  const ok = () => { if (!blocked) onDone(req.input ? text : true) }
  const cancel = () => onDone(req.input ? null : false)
  const onKeyDown = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); cancel() }
    else if (e.key === 'Enter' && !e.shiftKey && e.target.tagName !== 'TEXTAREA') { e.preventDefault(); ok() }
  }
  const danger = req.tone === 'danger'

  return (
    <div
      role="alertdialog" aria-modal="false" aria-label={req.title || 'تأكيد'} dir="rtl"
      onKeyDown={onKeyDown}
      className="fixed bottom-4 inset-x-0 mx-auto z-[1000] w-[min(36rem,calc(100%-2rem))]
                 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900
                 shadow-lg p-3 text-sm"
    >
      {req.title && <div className="font-bold mb-1">{req.title}</div>}
      <div className="whitespace-pre-line leading-relaxed text-gray-800 dark:text-gray-100">{req.message}</div>
      {req.input && (
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={req.input.placeholder || ''}
          className="mt-2 w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-transparent px-2 py-1.5"
        />
      )}
      <div className="mt-2 flex gap-2 justify-end">
        <button type="button" onClick={cancel}
                className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600">
          {req.cancelLabel || 'إلغاء'}
        </button>
        <button type="button" ref={okRef} onClick={ok} disabled={blocked}
                className={`px-3 py-1.5 rounded-lg text-white disabled:opacity-50 ${danger ? 'bg-red-600' : 'bg-brand-600'}`}>
          {req.confirmLabel || 'تأكيد'}
        </button>
      </div>
    </div>
  )
}

export function useConfirm() {
  const [req, setReq] = useState(null)
  const pending = useRef(null)          // the open request, so a newer one or an unmount settles it

  const settle = useCallback((value) => {
    const p = pending.current
    pending.current = null
    setReq(null)
    p?.resolve(value)
  }, [])

  const open = useCallback((message, opts = {}) => new Promise((resolve) => {
    if (pending.current) pending.current.resolve(pending.current.input ? null : false)
    const r = { message, ...opts, resolve, key: Date.now() + Math.random() }
    pending.current = r
    setReq(r)
  }), [])

  useEffect(() => () => {
    const p = pending.current
    pending.current = null
    p?.resolve(p.input ? null : false)
  }, [])

  const confirm = useCallback((message, opts) => open(message, opts), [open])
  // prompt() replacement: resolves the typed text ('' allowed unless input.required) or null on cancel
  const ask = useCallback((message, opts = {}) => open(message, { ...opts, input: opts.input || {} }), [open])

  const ui = req && typeof document !== 'undefined'
    ? createPortal(<ConfirmBar key={req.key} req={req} onDone={settle} />, document.body)
    : null

  return { confirm, ask, ui }
}
