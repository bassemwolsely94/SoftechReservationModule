import { describe, it, expect } from 'vitest'
import { itemsToReplay } from './offlineQueue'

describe('itemsToReplay (full audit FE-1: a shared phone never replays another user\'s writes)', () => {
  const items = [
    { id: 'b', ts: 2, userId: 7 },
    { id: 'a', ts: 1, userId: 7 },
    { id: 'c', ts: 3, userId: 9 },
    { id: 'old', ts: 0 },                 // queued before items recorded their user
  ]
  it('replays only the signed-in user\'s items, oldest first', () => {
    expect(itemsToReplay(items, 7).map(i => i.id)).toEqual(['a', 'b'])
    expect(itemsToReplay(items, 9).map(i => i.id)).toEqual(['c'])
  })
  it('replays nothing before anyone signs in', () => {
    expect(itemsToReplay(items, null)).toEqual([])
  })
})
