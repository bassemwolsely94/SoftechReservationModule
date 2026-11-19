// D-25: the app replaced window.confirm / prompt with inline confirms (frontend/src/components/
// InlineConfirm.jsx), so `page.on('dialog')` no longer sees them. This answers them the way the old
// dialog handler did — "OK", and a typed answer for an input:
//   • the non-modal bottom bar  [role=alertdialog][aria-modal=false] → fill an empty input, click its
//     last button (the confirm; the first is «إلغاء»);
//   • a two-step ConfirmButton  button[data-armed="1"] → the second click.
// The POS F10 send is armed by the hook, not a ConfirmButton: a live-send step must press F10 twice.
//
// Self-contained on purpose: Playwright serialises it into the page (context.addInitScript), and the
// vitest test runs the same function in jsdom.
export function installInlineConfirmAnswerer(answer) {
  const w = typeof window !== 'undefined' ? window : globalThis
  if (w.__uatInlineConfirm) return w.__uatInlineConfirm
  const DELAY = 30   // let React finish the render that opened it before clicking

  const fill = (input, value) => {
    const proto = Object.getPrototypeOf(input)
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    if (setter) setter.call(input, value); else input.value = value
    input.dispatchEvent(new Event('input', { bubbles: true }))
  }

  const tick = () => {
    for (const bar of document.querySelectorAll('[role="alertdialog"][aria-modal="false"]')) {
      if (bar.dataset.uatAnswered) continue
      bar.dataset.uatAnswered = '1'
      const input = bar.querySelector('input, textarea')
      if (input && !input.value) fill(input, answer)
      setTimeout(() => {
        const buttons = bar.querySelectorAll('button')
        const ok = buttons[buttons.length - 1]
        if (ok && !ok.disabled && bar.isConnected) ok.click()
      }, DELAY)
    }
    for (const b of document.querySelectorAll('button[data-armed]')) {
      if (b.dataset.armed === '1' && !b.dataset.uatAnswered) {
        b.dataset.uatAnswered = '1'
        setTimeout(() => { if (b.isConnected && b.dataset.armed === '1') b.click() }, DELAY)
      } else if (b.dataset.armed !== '1' && b.dataset.uatAnswered) {
        delete b.dataset.uatAnswered      // disarmed: the next arm on this button is answered again
      }
    }
  }

  const start = () => {
    const obs = new MutationObserver(tick)
    obs.observe(document.documentElement || document, {
      childList: true, subtree: true, attributes: true, attributeFilter: ['data-armed'],
    })
    tick()
    w.__uatInlineConfirm = { stop: () => { obs.disconnect(); delete w.__uatInlineConfirm } }
    return w.__uatInlineConfirm
  }
  if (document.documentElement) return start()
  document.addEventListener('DOMContentLoaded', start, { once: true })
  return null
}
