// ── Add to frontend/src/api/client.js ──

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
