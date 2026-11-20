import { describe, it, expect } from 'vitest'
import { canSetWebrtc } from './pbxAccess'

describe('canSetWebrtc', () => {
  it('follows the server flag', () => {
    expect(canSetWebrtc({ can_set_webrtc: true })).toBe(true)
    expect(canSetWebrtc({ can_set_webrtc: false })).toBe(false)
    expect(canSetWebrtc({ role: 'call_center' })).toBe(false)
    expect(canSetWebrtc(null)).toBe(false)
  })
})
