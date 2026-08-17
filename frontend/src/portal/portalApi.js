/**
 * portalApi.js — customer self-service portal API client.
 *
 * DELIBERATELY SEPARATE from src/api/client.js (the staff client):
 *  - its own axios instance + baseURL '/api/portal'
 *  - uses the custom `Portal` auth scheme, NOT `Bearer` (so a portal token can
 *    never be mistaken for / used as a staff JWT, and vice-versa)
 *  - reads/writes its OWN localStorage key (portal_session_token)
 *  - on 401 it redirects to /portal/login, NOT the staff /login
 */
import axios from 'axios'

const TOKEN_KEY = 'portal_session_token'

export const portalToken = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

const portal = axios.create({
  baseURL: '/api/portal',
  headers: { 'Content-Type': 'application/json' },
})

portal.interceptors.request.use(config => {
  const token = portalToken.get()
  if (token) config.headers.Authorization = `Portal ${token}`
  return config
})

portal.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      portalToken.clear()
      if (!window.location.pathname.startsWith('/portal/login') &&
          !window.location.pathname.startsWith('/portal/auth')) {
        window.location.href = '/portal/login'
      }
    }
    return Promise.reject(err)
  }
)

export const portalApi = {
  requestLink: (phone) => portal.post('/request-link/', { phone }),
  exchange:    (token) => portal.post('/auth/', { token }),
  me:          ()      => portal.get('/me/'),
  orders:      ()      => portal.get('/orders/'),
  loyalty:     ()      => portal.get('/loyalty/'),
  refills:     ()      => portal.get('/refills/'),
  reorder:     (data)  => portal.post('/reorder/', data),
}

export default portal
