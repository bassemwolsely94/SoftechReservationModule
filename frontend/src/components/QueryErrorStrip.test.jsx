// Full audit FE-7: a failed read must not look like "no data".
import { afterEach, describe, expect, it } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import QueryErrorStrip from './QueryErrorStrip'
import QueryState from './QueryState'
import { describeQueryError } from '../utils/queryErrors'

afterEach(cleanup)

const httpError = (status, data) => Object.assign(new Error(`HTTP ${status}`), { isAxiosError: true, response: { status, data } })

function Reader({ qk, fn, meta }) {
  const q = useQuery({ queryKey: [qk], queryFn: fn, meta, retry: false })
  return <div>{q.data ?? 'لا توجد سجلات'}</div>
}

function renderWith(children) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(<QueryClientProvider client={qc}><QueryErrorStrip />{children}</QueryClientProvider>)
  return { qc, ...utils }
}

describe('describeQueryError', () => {
  it('uses a short server message', () => {
    expect(describeQueryError(httpError(400, { detail: 'الفرع مطلوب' }))).toBe('الفرع مطلوب')
  })
  it('falls back to the status text, never an HTML page', () => {
    expect(describeQueryError(httpError(403, {}))).toBe('غير مسموح لك بعرض هذه البيانات')
    expect(describeQueryError(httpError(500, { detail: '<html>Server Error</html>' }))).toBe('خطأ في السيرفر (500)')
  })
  it('names a lost connection', () => {
    expect(describeQueryError({ isAxiosError: true, request: {} })).toBe('لا يوجد اتصال بالسيرفر')
  })
})

describe('QueryErrorStrip', () => {
  it('shows a failed read on the open screen, with the reason', async () => {
    renderWith(<Reader qk="a" fn={() => Promise.reject(httpError(403, {}))} />)
    const strip = await screen.findByTestId('query-error-strip')
    expect(strip.textContent).toContain('غير مسموح لك بعرض هذه البيانات')
  })

  it('stays quiet for session expiry (401) and for queries that show their own error', async () => {
    renderWith(<>
      <Reader qk="b" fn={() => Promise.reject(httpError(401, {}))} />
      <Reader qk="c" fn={() => Promise.reject(httpError(500, {}))} meta={{ ownErrorState: true }} />
    </>)
    await act(() => new Promise(r => setTimeout(r, 20)))
    expect(screen.queryByTestId('query-error-strip')).toBeNull()
  })

  it('clears when the user leaves the screen', async () => {
    const { qc, rerender } = renderWith(<Reader qk="d" fn={() => Promise.reject(httpError(500, {}))} />)
    await screen.findByTestId('query-error-strip')
    rerender(<QueryClientProvider client={qc}><QueryErrorStrip /></QueryClientProvider>)
    await waitFor(() => expect(screen.queryByTestId('query-error-strip')).toBeNull())
  })

  it('clears after a successful retry', async () => {
    let fail = true
    renderWith(<Reader qk="e" fn={() => (fail ? Promise.reject(httpError(503, {})) : Promise.resolve('ok'))} />)
    await screen.findByTestId('query-error-strip')
    fail = false
    fireEvent.click(screen.getByText('إعادة المحاولة'))
    await waitFor(() => expect(screen.queryByTestId('query-error-strip')).toBeNull())
    expect(await screen.findByText('ok')).toBeTruthy()
  })
})

describe('QueryState', () => {
  const base = { isPending: false, isError: false, data: [], refetch: () => {} }

  it('shows the error, not the empty text, when the read failed', () => {
    render(<QueryState q={{ ...base, isError: true, data: undefined, error: httpError(500, {}) }} isEmpty empty="لا توجد طلبات" />)
    expect(screen.getByTestId('query-state-error').textContent).toContain('خطأ في السيرفر (500)')
    expect(screen.queryByText('لا توجد طلبات')).toBeNull()
  })

  it('shows loading, not the empty text, while loading', () => {
    render(<QueryState q={{ ...base, isPending: true, data: undefined }} isEmpty empty="لا توجد طلبات" />)
    expect(screen.getByTestId('query-state-loading')).toBeTruthy()
    expect(screen.queryByText('لا توجد طلبات')).toBeNull()
  })

  it('shows the empty text only after a successful empty read', () => {
    render(<QueryState q={base} isEmpty empty="لا توجد طلبات" />)
    expect(screen.getByText('لا توجد طلبات')).toBeTruthy()
  })

  it('keeps old rows on a failed refresh and says they are old', () => {
    render(<QueryState q={{ ...base, isError: true, data: [1], error: httpError(502, {}) }} isEmpty={false}><div>row</div></QueryState>)
    expect(screen.getByText('row')).toBeTruthy()
    expect(screen.getByTestId('query-state-stale').textContent).toContain('السيرفر لا يرد الآن')
  })
})
