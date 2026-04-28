import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT token to every request
api.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-refresh on 401
api.interceptors.response.use(
  res => res,
  async err => {
    const original = err.config
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          const { data } = await axios.post('/api/auth/refresh/', { refresh })
          localStorage.setItem('access_token', data.access)
          original.headers.Authorization = `Bearer ${data.access}`
          return api(original)
        } catch {
          localStorage.clear()
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(err)
  }
)

export default api

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  login: (username, password) => api.post('/auth/login/', { username, password }),
  me: () => api.get('/auth/me/'),
}

// ── Reservations ──────────────────────────────────────────────────────────────

export const reservationsApi = {
  list:         (params) => api.get('/reservations/', { params }),
  get:          (id) => api.get(`/reservations/${id}/`),
  create:       (data) => api.post('/reservations/', data),
  update:       (id, data) => api.patch(`/reservations/${id}/`, data),
  changeStatus: (id, status, note = '') =>
    api.post(`/reservations/${id}/change-status/`, { status, note }),
  dashboard:    (params) => api.get('/reservations/dashboard/', { params }),

  // Chatter
  activities:   (id) => api.get(`/reservations/${id}/activities/`),
  logActivity:  (id, formData) =>
    api.post(`/reservations/${id}/log/`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
}

// ── Customers ─────────────────────────────────────────────────────────────────

export const customersApi = {
  list:       (params) => api.get('/customers/', { params }),
  get:        (id) => api.get(`/customers/${id}/`),
  create:     (data) => api.post('/customers/', data),
  update:     (id, data) => api.patch(`/customers/${id}/`, data),

  // purchases — pass doc_code param if filtering
  purchases:  (id, docCode) =>
    api.get(`/customers/${id}/purchases/`,
      docCode ? { params: { doc_code: docCode } } : {}),

  reservations: (id) => api.get(`/customers/${id}/reservations/`),
  topItems:     (id) => api.get(`/customers/${id}/top_items/`),
  addNote:      (id, note) => api.post(`/customers/${id}/notes/`, { note }),
  deleteNote:   (customerId, noteId) =>
    api.delete(`/customers/${customerId}/notes/${noteId}/`),
  updateConditions: (id, chronic_conditions) =>
    api.patch(`/customers/${id}/update_conditions/`, { chronic_conditions }),
}


// ── Items ─────────────────────────────────────────────────────────────────────

export const itemsApi = {
  list:  (params) => api.get('/items/', { params }),
  get:   (id) => api.get(`/items/${id}/`),
  stock: (id) => api.get(`/items/${id}/stock/`),
}

// ── Branches ──────────────────────────────────────────────────────────────────

export const branchesApi = {
  list: () => api.get('/branches/'),
}

// ── Sync ──────────────────────────────────────────────────────────────────────

export const syncApi = {
  status:  () => api.get('/sync/status/'),
  trigger: (full = false) => api.post('/sync/trigger/', { full }),
  logs:    () => api.get('/sync/logs/'),
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export const dashboardApi = {
  summary:   (params) => api.get('/dashboard/summary/', { params }),
  followups: ()       => api.get('/dashboard/followups/'),
  purchasing:(days)   => api.get('/dashboard/purchasing/', { params: { days } }),
}


// ── Notifications ─────────────────────────────────────────────────────────────

export const notificationsApi = {
  list:       () => api.get('/notifications/'),
  unreadCount:() => api.get('/notifications/unread-count/'),
  markRead:   (id) => api.post(`/notifications/${id}/read/`),
  markAllRead:() => api.post('/notifications/mark-all-read/'),
}

// ── Transfers ─────────────────────────────────────────────────────────────────

export const transfersApi = {
  // CRUD
  list:    (params) => api.get('/transfers/', { params }),
  get:     (id)     => api.get(`/transfers/${id}/`),
  create:  (data)   => api.post('/transfers/', data),
  update:  (id, data) => api.patch(`/transfers/${id}/`, data),
  delete:  (id)     => api.delete(`/transfers/${id}/`),

  // State machine actions
  submit:     (id)         => api.post(`/transfers/${id}/submit/`),
  approve:    (id)         => api.post(`/transfers/${id}/approve/`),
  reject:     (id, data)   => api.post(`/transfers/${id}/reject/`, data),
  revision:   (id, data)   => api.post(`/transfers/${id}/revision/`, data),
  sendToERP:  (id, data)   => api.post(`/transfers/${id}/send-to-erp/`, data),
  complete:   (id)         => api.post(`/transfers/${id}/complete/`),
  cancel:     (id)         => api.post(`/transfers/${id}/cancel/`),

  // Item management
  addItem:    (id, data)   => api.post(`/transfers/${id}/items/`, data),
  removeItem: (id, itemId) => api.delete(`/transfers/${id}/items/${itemId}/`),
  updateItem: (id, itemId, data) => api.patch(`/transfers/${id}/items/${itemId}/`, data),

  // Chatter
  sendMessage: (id, data)  => api.post(`/transfers/${id}/messages/`, data),

  // Stock lookup
  itemStock:  (itemId)     => api.get('/transfers/item_stock/', { params: { item_id: itemId } }),
}




export const purchasingApi = {
  dashboard: (days = 30) =>
    api.get('/dashboard/purchasing/', { params: { days } }),
}


export const demandApi = {
  // CRUD
  list:   (params) => api.get('/demand/', { params }),
  get:    (id)     => api.get(`/demand/${id}/`),
  create: (data)   => api.post('/demand/', data),
  update: (id, data) => api.patch(`/demand/${id}/`, data),

  // State machine
  assign:          (id, data) => api.post(`/demand/${id}/assign/`, data),
  followUp:        (id, data) => api.post(`/demand/${id}/follow-up/`, data),
  stockETA:        (id, data) => api.post(`/demand/${id}/stock-eta/`, data),
  suggestTransfer: (id, data) => api.post(`/demand/${id}/suggest-transfer/`, data),
  flagPurchasing:  (id, data) => api.post(`/demand/${id}/flag-purchasing/`, data),
  fulfill:         (id, data) => api.post(`/demand/${id}/fulfill/`, data),
  markLost:        (id, data) => api.post(`/demand/${id}/lost/`, data),
  cancel:          (id, data) => api.post(`/demand/${id}/cancel/`, data),

  // Items
  addItem:    (id, data)   => api.post(`/demand/${id}/items/`, data),
  removeItem: (id, itemId) => api.delete(`/demand/${id}/items/${itemId}/`),

  // Logs
  getLogs: (id)         => api.get(`/demand/${id}/logs/`),
  addLog:  (id, data)   => api.post(`/demand/${id}/logs/`, data),

  // Follow-ups
  getFollowups:      (id)         => api.get(`/demand/${id}/followups/`),
  scheduleFollowup:  (id, data)   => api.post(`/demand/${id}/schedule-followup/`, data),
  completeFollowup:  (id, taskId, data) => api.post(`/demand/${id}/followups/${taskId}/complete/`, data),

  // ERP
  enrichFromERP: (id)    => api.post(`/demand/${id}/enrich/`),
  erpLookup:     (params) => api.get('/demand/erp-lookup/', { params }),

  // Dashboard
  dashboard: (params) => api.get('/demand/dashboard/', { params }),
}


