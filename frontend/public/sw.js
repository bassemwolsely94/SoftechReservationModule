/*
 * sw.js — service worker for Web Push (VAPID).
 *
 * Handles two events:
 *   • push             → render a system notification from the pushed payload
 *   • notificationclick→ focus an existing app tab (or open one) at the deep link
 *
 * The payload is the JSON sent by the backend's send_web_push():
 *   { "title": "...", "body": "...", "url": "/m/notifications" }
 *
 * NOTE (iOS): Safari only delivers Web Push to an INSTALLED PWA (Add to Home
 * Screen) on iOS/iPadOS 16.4+. Desktop Chrome/Firefox/Edge and Android Chrome
 * deliver in a normal browser tab.
 */

// Activate immediately on install/update so a fresh SW controls pages right away.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (e) {
    // Non-JSON payload — fall back to raw text as the body.
    data = { body: event.data ? event.data.text() : '' }
  }

  const title = data.title || 'صيدليات الرزيقي'
  const options = {
    body: data.body || '',
    dir: 'rtl',
    lang: 'ar',
    tag: data.tag || 'elrezeiky-notification',
    renotify: true,
    data: { url: data.url || '/m/notifications' },
  }
  // Icons are optional — only set when the payload provides one (no app icon
  // assets are shipped yet, so a hardcoded path would 404).
  if (data.icon) options.icon = data.icon
  if (data.badge) options.badge = data.badge

  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = (event.notification.data && event.notification.data.url) || '/m/notifications'

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      // Focus an already-open app tab and navigate it to the target.
      for (const client of clientList) {
        if ('focus' in client) {
          client.focus()
          if ('navigate' in client) {
            client.navigate(targetUrl).catch(() => {})
          }
          return
        }
      }
      // No open tab → open a new one.
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl)
      }
    })
  )
})
