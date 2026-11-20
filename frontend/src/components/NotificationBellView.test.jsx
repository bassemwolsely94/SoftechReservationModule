// C26 / D-19: the bell opens on «يحتاج إجراء», «الكل» is one click away and the choice is saved per user.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../api/client', () => ({
  notificationsApi: {
    getPreferences: vi.fn(),
    updatePreferences: vi.fn(() => Promise.resolve({ data: {} })),
    list: vi.fn(),
    categoryCounts: vi.fn(() => Promise.resolve({ data: { bell: 5, action: 2, visible: [] } })),
    markRead: vi.fn(() => Promise.resolve({})),
    markAllRead: vi.fn(() => Promise.resolve({ data: { marked: 0 } })),
    reminders: vi.fn(() => Promise.resolve({ data: [] })),
  },
  refreshSession: vi.fn(() => Promise.resolve()),
}))

import { notificationsApi } from '../api/client'
import NotificationPanel from './NotificationPanel'
import useNotificationStore from '../store/notificationStore'
import useAuthStore from '../store/authStore'
import { inBellView, bellCountFor, useNotificationSocket } from '../hooks/useNotificationSocket'

afterEach(() => { cleanup(); vi.clearAllMocks() })

const row = (over = {}) => ({
  id: 1, title: 'إشعار', body: '', is_read: false, created_at: new Date().toISOString(),
  notification_type: 'announcement', category: 'global', is_action: false, ...over,
})

describe('inBellView / bellCountFor', () => {
  it('action view = is_action rows from any category, even a quiet feed', () => {
    expect(inBellView(row({ is_action: true, category: 'mentions' }), 'action')).toBe(true)
    expect(inBellView(row({ is_action: false, category: 'global' }), 'action')).toBe(false)
  })
  it('all view = the bell categories only (quiet feeds stay out)', () => {
    expect(inBellView(row({ category: 'global' }), 'all')).toBe(true)
    expect(inBellView(row({ category: 'monitoring' }), 'all')).toBe(false)
    expect(inBellView(row({ category: 'mentions', is_action: true }), 'all')).toBe(false)
  })
  it('badge follows the view', () => {
    expect(bellCountFor({ bell: 7, action: 3 }, 'action')).toBe(3)
    expect(bellCountFor({ bell: 7, action: 3 }, 'all')).toBe(7)
    expect(bellCountFor(null, 'action')).toBe(0)
  })
})

describe('NotificationPanel view tabs', () => {
  function renderPanel(props) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <NotificationPanel notifications={[]} unreadCount={0} onMarkRead={() => {}} onMarkAllRead={() => {}}
          onDelete={() => {}} onClickNotif={() => {}} onClose={() => {}} {...props} />
      </QueryClientProvider>,
    )
  }

  beforeEach(() => { useNotificationStore.setState({ bellCounts: { bell: 9, action: 2 } }) })

  it('shows both tabs with their counts and marks the current one', () => {
    renderPanel({ view: 'action', unreadCount: 2, onViewChange: () => {} })
    expect(screen.getByTestId('bell-view-action').textContent).toContain('يحتاج إجراء (2)')
    expect(screen.getByTestId('bell-view-all').textContent).toContain('الكل (9)')
    expect(screen.getByTestId('bell-view-action').getAttribute('aria-pressed')).toBe('true')
  })

  it('clicking «الكل» asks to switch the view', () => {
    const onViewChange = vi.fn()
    renderPanel({ view: 'action', onViewChange })
    fireEvent.click(screen.getByTestId('bell-view-all'))
    expect(onViewChange).toHaveBeenCalledWith('all')
  })

  it('an empty action view says so and offers everything in one click', () => {
    const onViewChange = vi.fn()
    renderPanel({ view: 'action', onViewChange })
    expect(screen.getByText('لا شيء يحتاج إجراء الآن')).toBeTruthy()
    fireEvent.click(screen.getByText('عرض كل الإشعارات'))
    expect(onViewChange).toHaveBeenCalledWith('all')
  })

  it('unread-only narrows the current list', () => {
    renderPanel({
      view: 'all', onViewChange: () => {},
      notifications: [row({ id: 1, title: 'جديد' }), row({ id: 2, title: 'قديم', is_read: true })],
    })
    expect(screen.queryByText('قديم')).toBeTruthy()
    fireEvent.click(screen.getByText('غير مقروء فقط'))
    expect(screen.queryByText('قديم')).toBeNull()
    expect(screen.queryByText('جديد')).toBeTruthy()
  })
})

describe('useNotificationSocket view', () => {
  class FakeSocket {
    static OPEN = 1
    constructor() { this.readyState = 0; FakeSocket.last = this }
    send() {}
    close() {}
  }

  beforeEach(() => {
    vi.stubGlobal('WebSocket', FakeSocket)
    useAuthStore.setState({ isAuthenticated: true })   // socket path, not the logged-out poll
    notificationsApi.list.mockResolvedValue({ data: [] })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('loads the saved view before the first list call', async () => {
    notificationsApi.getPreferences.mockResolvedValue({ data: { bell_view: 'all' } })
    const { result } = renderHook(() => useNotificationSocket())
    await waitFor(() => expect(notificationsApi.list).toHaveBeenCalled())
    expect(notificationsApi.list.mock.calls[0][0]).toMatchObject({ view: 'all' })
    expect(result.current.view).toBe('all')
  })

  it('defaults to action items when nothing is saved', async () => {
    notificationsApi.getPreferences.mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useNotificationSocket())
    await waitFor(() => expect(notificationsApi.list).toHaveBeenCalled())
    expect(notificationsApi.list.mock.calls[0][0]).toMatchObject({ view: 'action' })
    expect(result.current.view).toBe('action')
  })

  it('switching saves the choice, reloads the list and «قراءة الكل» marks only that view', async () => {
    notificationsApi.getPreferences.mockResolvedValue({ data: { bell_view: 'action' } })
    const { result } = renderHook(() => useNotificationSocket())
    await waitFor(() => expect(notificationsApi.list).toHaveBeenCalledTimes(1))
    act(() => result.current.setView('all'))
    expect(notificationsApi.updatePreferences).toHaveBeenCalledWith({ bell_view: 'all' })
    await waitFor(() => expect(notificationsApi.list).toHaveBeenCalledTimes(2))
    expect(notificationsApi.list.mock.calls[1][0]).toMatchObject({ view: 'all' })
    await act(() => result.current.markAllRead())   // socket not open → REST
    expect(notificationsApi.markAllRead).toHaveBeenCalledWith({ view: 'all' })
  })
})
