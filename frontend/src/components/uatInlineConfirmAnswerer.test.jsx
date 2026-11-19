// The UAT harness answers the app's inline confirms (uat/lib/inlineConfirmAnswerer.js) the way it used
// to accept native dialogs. Run it here against the real ConfirmButton / confirm bar so a change to
// either side breaks a fast test instead of a long UAT run.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfirmButton, useConfirm } from './InlineConfirm'
import { installInlineConfirmAnswerer } from '../../uat/lib/inlineConfirmAnswerer.js'

afterEach(() => { window.__uatInlineConfirm?.stop(); cleanup() })

function Bar({ onResult, mode = 'confirm', opts }) {
  const { confirm, ask, ui } = useConfirm()
  return (
    <div>
      {ui}
      <button onClick={async () => onResult(await (mode === 'ask' ? ask : confirm)('متابعة؟', opts))}>go</button>
    </div>
  )
}

describe('UAT inline-confirm answerer', () => {
  it('confirms the bottom bar (the old dialog.accept())', async () => {
    installInlineConfirmAnswerer('UAT-W5a done')
    const onResult = vi.fn()
    render(<Bar onResult={onResult} opts={{ tone: 'danger', confirmLabel: 'حذف' }} />)
    fireEvent.click(screen.getByText('go'))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('types the UAT answer into an ask() input, even a required one', async () => {
    installInlineConfirmAnswerer('UAT-W5a done')
    const onResult = vi.fn()
    render(<Bar mode="ask" onResult={onResult} opts={{ input: { required: true } }} />)
    fireEvent.click(screen.getByText('go'))
    await waitFor(() => expect(onResult).toHaveBeenCalledWith('UAT-W5a done'))
  })

  it('gives a two-step ConfirmButton its second click — every time it is armed', async () => {
    installInlineConfirmAnswerer('x')
    const onConfirm = vi.fn()
    render(<ConfirmButton onConfirm={onConfirm}>حذف</ConfirmButton>)
    fireEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(2))
  })

  it('installs once per page', () => {
    const a = installInlineConfirmAnswerer('x')
    expect(installInlineConfirmAnswerer('y')).toBe(a)
  })
})
