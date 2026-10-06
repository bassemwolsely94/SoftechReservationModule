/* portal-sw.js — minimal service worker for the customer portal PWA.
 *
 * Scope is implicitly the root, but the app only registers it from /portal pages.
 * Strategy: network-first for navigations (so the app shell stays fresh), with a
 * cached fallback so /portal is launchable offline once visited. API calls are
 * never cached (always fetched live). */
const CACHE = 'portal-shell-v1'
const SHELL = ['/portal', '/portal/login', '/manifest.webmanifest', '/portal-icon.svg']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}))
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
    ),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  // Never intercept API traffic.
  if (url.pathname.startsWith('/api/')) return
  if (e.request.mode !== 'navigate') return

  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone()
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {})
        return res
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match('/portal'))),
  )
})
