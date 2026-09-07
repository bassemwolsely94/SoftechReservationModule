/**
 * push.js — Web Push (VAPID) registration + subscription helpers.
 *
 * Flow:
 *   1. register the service worker (frontend/public/sw.js)
 *   2. fetch the server VAPID public key
 *   3. request Notification permission
 *   4. subscribe via the PushManager and POST the subscription to the backend
 *
 * `initPush()`   — call once after login. Re-syncs an existing subscription when
 *                  permission was already granted (no prompt). Silent otherwise.
 * `enablePush()` — call from a user gesture (toggle/button). Prompts for
 *                  permission and subscribes. Returns true on success.
 * `disablePush()`— unsubscribe locally + tell the backend to forget the endpoint.
 *
 * NOTE (iOS): Safari only delivers Web Push to an INSTALLED PWA (Add to Home
 * Screen) on iOS/iPadOS 16.4+. In a plain iOS Safari tab subscription will fail.
 */
import { notificationsApi } from './api/client'

export function pushSupported() {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

// base64url (VAPID public key) → Uint8Array, as required by applicationServerKey.
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(base64)
  const output = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i)
  return output
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return null
  try {
    return await navigator.serviceWorker.register('/sw.js')
  } catch (e) {
    console.warn('[push] SW registration failed', e)
    return null
  }
}

async function getVapidKey() {
  try {
    const { data } = await notificationsApi.vapidPublicKey()
    if (!data?.enabled || !data?.public_key) return null
    return data.public_key
  } catch {
    return null
  }
}

async function subscribeAndSync(registration, vapidKey) {
  let sub = await registration.pushManager.getSubscription()
  if (!sub) {
    sub = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey),
    })
  }
  await notificationsApi.pushSubscribe(sub.toJSON())
  return true
}

/**
 * Silent re-sync after login. Only subscribes if the user has ALREADY granted
 * notification permission — never prompts. Safe to call on every app load.
 */
export async function initPush() {
  if (!pushSupported()) return false
  if (Notification.permission !== 'granted') return false

  const vapidKey = await getVapidKey()
  if (!vapidKey) return false

  const registration = await registerServiceWorker()
  if (!registration) return false

  try {
    return await subscribeAndSync(registration, vapidKey)
  } catch (e) {
    console.warn('[push] initPush subscribe failed', e)
    return false
  }
}

/**
 * Explicit opt-in (call from a user gesture). Prompts for permission and
 * subscribes. Returns true on success, false otherwise.
 */
export async function enablePush() {
  if (!pushSupported()) {
    return { ok: false, reason: 'unsupported' }
  }

  const vapidKey = await getVapidKey()
  if (!vapidKey) return { ok: false, reason: 'disabled' }

  let permission = Notification.permission
  if (permission === 'default') {
    permission = await Notification.requestPermission()
  }
  if (permission !== 'granted') {
    return { ok: false, reason: 'denied' }
  }

  const registration = await registerServiceWorker()
  if (!registration) return { ok: false, reason: 'sw_failed' }

  try {
    await subscribeAndSync(registration, vapidKey)
    return { ok: true }
  } catch (e) {
    console.warn('[push] enablePush subscribe failed', e)
    return { ok: false, reason: 'subscribe_failed' }
  }
}

/**
 * Turn push off on this device: drop the browser subscription and tell the
 * backend to forget the endpoint.
 */
export async function disablePush() {
  if (!('serviceWorker' in navigator)) return false
  try {
    const registration = await navigator.serviceWorker.getRegistration()
    const sub = registration && (await registration.pushManager.getSubscription())
    if (sub) {
      const endpoint = sub.endpoint
      await sub.unsubscribe().catch(() => {})
      await notificationsApi.pushUnsubscribe({ endpoint }).catch(() => {})
    }
    return true
  } catch (e) {
    console.warn('[push] disablePush failed', e)
    return false
  }
}

/** Current opt-in state for UI toggles: 'unsupported' | 'denied' | 'on' | 'off'. */
export async function pushStatus() {
  if (!pushSupported()) return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  try {
    const registration = await navigator.serviceWorker.getRegistration()
    const sub = registration && (await registration.pushManager.getSubscription())
    return sub ? 'on' : 'off'
  } catch {
    return 'off'
  }
}
