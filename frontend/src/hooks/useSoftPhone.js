/**
 * Browser phone (WebRTC) over Issabel's secure websocket, via JsSIP.
 * One shared SIP connection per tab; components subscribe to its state.
 * Config (incl. the agent's own SIP password) comes from /api/pbx/webrtc/config/
 * and is kept in memory only.
 */
import { useEffect, useState } from 'react'
import { pbxApi } from '../api/client'

let JsSIP = null
let ua = null
let session = null
let remoteAudio = null
let ringTimer = null
let audioCtx = null
let started = false

// Ring tone generated in code (like the notification alarm) — no audio file needed
function beep(freq, at, len) {
  const osc = audioCtx.createOscillator(), gain = audioCtx.createGain()
  osc.frequency.value = freq
  gain.gain.setValueAtTime(0.15, audioCtx.currentTime + at)
  gain.gain.setValueAtTime(0, audioCtx.currentTime + at + len)
  osc.connect(gain).connect(audioCtx.destination)
  osc.start(audioCtx.currentTime + at)
  osc.stop(audioCtx.currentTime + at + len)
}

function startRing() {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)()
    const ring = () => { beep(440, 0, 0.4); beep(480, 0.5, 0.4) }
    ring()
    ringTimer = setInterval(ring, 2000)
  } catch { /* audio blocked until the first click — the visual alert still shows */ }
}
const listeners = new Set()

let state = {
  available: false,     // configured for this user
  reason: '',           // why not (not_configured / no_extension / not_enabled / no_password)
  registered: false,
  error: '',
  call: null,           // { direction, number, status: ringing|connecting|active|held, muted, startedAt }
}

function set(patch) {
  state = { ...state, ...patch }
  listeners.forEach(fn => fn(state))
}

function setCall(patch) {
  set({ call: patch === null ? null : { ...(state.call || {}), ...patch } })
}

function stopRing() {
  if (ringTimer) { clearInterval(ringTimer); ringTimer = null }
}

function bindSession(s, direction) {
  session = s
  const number = s.remote_identity?.uri?.user || ''
  setCall({ direction, number, status: direction === 'incoming' ? 'ringing' : 'connecting',
            muted: false, startedAt: null })
  if (direction === 'incoming') startRing()

  s.on('peerconnection', (e) => {
    e.peerconnection.addEventListener('track', (ev) => {
      if (remoteAudio) { remoteAudio.srcObject = ev.streams[0]; remoteAudio.play().catch(() => {}) }
    })
  })
  s.on('accepted', () => { stopRing(); setCall({ status: 'active', startedAt: Date.now() }) })
  s.on('confirmed', () => { stopRing(); setCall({ status: 'active', startedAt: state.call?.startedAt || Date.now() }) })
  s.on('hold', () => setCall({ status: 'held' }))
  s.on('unhold', () => setCall({ status: 'active' }))
  const end = () => { stopRing(); session = null; setCall(null) }
  s.on('ended', end)
  s.on('failed', end)
}

async function start() {
  if (started) return
  started = true
  let cfg
  try {
    cfg = (await pbxApi.webrtcConfig()).data
  } catch {
    set({ available: false, reason: 'error' })
    return
  }
  if (!cfg.enabled) { set({ available: false, reason: cfg.reason }); return }

  JsSIP = (await import('jssip')).default
  remoteAudio = new Audio()
  remoteAudio.autoplay = true

  const socket = new JsSIP.WebSocketInterface(cfg.wss_url)
  ua = new JsSIP.UA({
    sockets: [socket], uri: cfg.sip_uri, authorization_user: cfg.authorization_user,
    password: cfg.password, display_name: cfg.display_name, session_timers: false,
    register: true,
  })
  set({ available: true, reason: '' })
  ua.on('registered', () => set({ registered: true, error: '' }))
  ua.on('unregistered', () => set({ registered: false }))
  ua.on('registrationFailed', (e) => set({ registered: false, error: e.cause || 'فشل التسجيل' }))
  ua.on('disconnected', () => set({ registered: false, error: 'انقطع الاتصال بالسنترال' }))
  ua.on('newRTCSession', (e) => {
    if (session && e.originator === 'remote') { e.session.terminate({ status_code: 486 }); return }  // busy
    bindSession(e.session, e.originator === 'remote' ? 'incoming' : 'outgoing')
  })
  ua.start()
}

const mediaOpts = { mediaConstraints: { audio: true, video: false } }

export const softPhone = {
  isReady: () => !!(ua && state.registered && !session),
  call(number) {
    if (!softPhone.isReady()) return false
    ua.call(`sip:${number}@${ua.configuration.uri.host}`, mediaOpts)
    return true
  },
  answer() { session?.answer(mediaOpts) },
  hangup() { try { session?.terminate() } catch { /* already ended */ } },
  toggleMute() {
    if (!session) return
    if (state.call?.muted) { session.unmute({ audio: true }); setCall({ muted: false }) }
    else { session.mute({ audio: true }); setCall({ muted: true }) }
  },
  toggleHold() {
    if (!session) return
    if (state.call?.status === 'held') session.unhold(); else session.hold()
  },
  transfer(target) {
    if (!session || !target) return
    session.refer(`sip:${target}@${ua.configuration.uri.host}`)
  },
  dtmf(digit) { session?.sendDTMF(digit) },
}

export default function useSoftPhone() {
  const [s, setS] = useState(state)
  useEffect(() => {
    start()
    listeners.add(setS)
    return () => listeners.delete(setS)
  }, [])
  return s
}
